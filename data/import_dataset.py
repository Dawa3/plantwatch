#!/usr/bin/env python3
"""ETL: load the AI4I 2020 CSV into Redis.

Run from the service zone (the only zone the firewall lets talk to Redis):
    sudo ip netns exec pw-api env REDIS_HOST=10.14.3.10 REDIS_PASSWORD=... \
        .venv/bin/python data/import_dataset.py [--force]

Transformation
  * The dataset has 10,000 independent process observations and no machine or
    time column. Rows are dealt round-robin to 20 simulated machines (M01..M20)
    and given synthetic timestamps one minute apart. machine_id and ts are
    therefore SYNTHETIC; the sensor values and failure labels are from the dataset.
  * Each row becomes one entry in the stream telemetry:{machine}.
  * Each row whose dataset label marks a failure becomes one entry in `alerts`
    (source=dataset-label).
"""
import argparse
import csv
import os
import subprocess
import sys
import time

import redis

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_CSV = os.path.join(HERE, "ai4i2020.csv")
SYN_CSV = os.path.join(HERE, "synthetic_ai4i.csv")
N_MACHINES = 20
FAILURE_MODES = ("TWF", "HDF", "PWF", "OSF", "RNF")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    ap.add_argument("--force", action="store_true", help="wipe the database and import again")
    a = ap.parse_args()

    if a.csv:
        path, source = a.csv, "ai4i2020"
    elif os.path.exists(REAL_CSV):
        path, source = REAL_CSV, "ai4i2020"
    else:
        if not os.path.exists(SYN_CSV):
            subprocess.check_call([sys.executable, os.path.join(HERE, "make_synthetic.py"), "--out", SYN_CSV])
        path, source = SYN_CSV, "synthetic-generator"
        print("NOTE: data/ai4i2020.csv not found - importing generated records (source=synthetic-generator).")

    r = redis.Redis(host=os.environ.get("REDIS_HOST", "10.14.3.10"),
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    password=os.environ.get("REDIS_PASSWORD") or None, decode_responses=True)

    if r.hget("stats", "imported_rows") and not a.force:
        print("Database already holds an import (use --force to reload).")
        return
    if a.force:
        r.flushdb()

    t0 = time.time()
    base_ts = int(t0) - 10000 * 60          # history ends "now"
    rows = alerts = 0
    latest = {}
    pipe = r.pipeline(transaction=False)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            udi = int(row["UDI"])
            mid = f"M{(udi - 1) % N_MACHINES + 1:02d}"
            ts = base_ts + udi * 60
            rec = {"ts": ts, "type": row["Type"],
                   "air_temp_k": float(row["Air temperature [K]"]),
                   "process_temp_k": float(row["Process temperature [K]"]),
                   "rpm": float(row["Rotational speed [rpm]"]),
                   "torque_nm": float(row["Torque [Nm]"]),
                   "tool_wear_min": float(row["Tool wear [min]"]),
                   "source": source, "udi": udi, "failure": row["Machine failure"]}
            pipe.xadd(f"telemetry:{mid}", rec, id=f"{ts * 1000}-{udi}")
            latest[mid] = rec
            rows += 1
            if row["Machine failure"] == "1":
                modes = [m for m in FAILURE_MODES if row.get(m) == "1"] or ["UNSPECIFIED"]
                for i, m in enumerate(modes):
                    pipe.xadd("alerts", {"machine_id": mid, "rule": m,
                                         "detail": f"labelled failure in dataset row {udi}",
                                         "sensor_ts": ts, "received_ts": ts,
                                         "source": "dataset-label"}, id=f"{ts * 1000}-{i}")
                    alerts += 1
            if rows % 1000 == 0:
                pipe.execute()
    pipe.execute()

    pipe = r.pipeline()
    counts = {}
    for mid, rec in latest.items():
        counts[mid] = r.xlen(f"telemetry:{mid}")
        pipe.sadd("machines", mid)
        pipe.hset(f"machine:{mid}", mapping={
            "machine_id": mid, "type": rec["type"], "last_ts": rec["ts"], "last_source": source,
            "air_temp_k": rec["air_temp_k"], "process_temp_k": rec["process_temp_k"],
            "rpm": rec["rpm"], "torque_nm": rec["torque_nm"], "tool_wear_min": rec["tool_wear_min"],
            "status": "ok", "readings": counts[mid], "tool_wear_limit": 200})
    pipe.hset("stats", mapping={"imported_rows": rows, "import_source": source,
                                "imported_alerts": alerts, "imported_at": int(t0)})
    pipe.hincrby("stats", "readings_total", rows)
    pipe.hincrby("stats", "alerts_total", alerts)
    pipe.execute()
    print(f"Imported {rows} readings for {len(latest)} machines and {alerts} labelled-failure alerts "
          f"from {os.path.basename(path)} (source={source}) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
