#!/usr/bin/env python3
"""Machine simulator: replay dataset rows as live telemetry from the plant zone.

    sudo ip netns exec pw-plant .venv/bin/python client/replay.py --count 200 --rate 20

Rows come from data/ai4i2020.csv (or the generated fallback). The sensor values
are historical; machine id and send time are simulated, and every record is
labelled source=replay.
"""
import argparse
import csv
import os
import time

from common import ROOT, new_client, timed_request


def rows(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            yield row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--rate", type=float, default=20.0, help="readings per second")
    ap.add_argument("--machines", type=int, default=20)
    ap.add_argument("--offset", type=int, default=0, help="skip this many dataset rows first")
    a = ap.parse_args()

    path = os.path.join(ROOT, "data", "ai4i2020.csv")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "data", "synthetic_ai4i.csv")

    sent = ok = alerts = 0
    lat = []
    t0 = time.time()
    with new_client() as c:
        for i, row in enumerate(rows(path)):
            if i < a.offset:
                continue
            if sent >= a.count:
                break
            mid = f"M{int(row['UDI']) % a.machines + 1:02d}"
            body = {"machine_id": mid, "type": row["Type"],
                    "air_temp_k": float(row["Air temperature [K]"]),
                    "process_temp_k": float(row["Process temperature [K]"]),
                    "rpm": float(row["Rotational speed [rpm]"]),
                    "torque_nm": float(row["Torque [Nm]"]),
                    "tool_wear_min": float(row["Tool wear [min]"]),
                    "ts": time.time(), "source": "replay"}
            res = timed_request(c, "POST", "/telemetry", json=body)
            sent += 1
            if res["ok"]:
                ok += 1
                lat.append(res["total_ms"])
                for al in res["_resp"].json()["alerts"]:
                    alerts += 1
                    print(f"  ALERT {mid} {al['rule']}: {al['detail']}")
            else:
                print(f"  send failed: status={res['status']} {res['error']}")
            # pace the stream
            delay = t0 + sent / a.rate - time.time()
            if delay > 0:
                time.sleep(delay)
    dur = time.time() - t0
    lat.sort()
    med = lat[len(lat) // 2] if lat else float("nan")
    print(f"sent {sent} readings in {dur:.1f}s ({sent / dur:.1f}/s), {ok} stored, "
          f"{sent - ok} failed, {alerts} alerts, median latency {med:.1f} ms")


if __name__ == "__main__":
    main()
