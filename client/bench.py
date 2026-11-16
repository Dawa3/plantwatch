#!/usr/bin/env python3
"""Repeatable benchmark workload, run from the plant (client) zone.

The workload is identical on every run (fixed seed), so baseline, degraded
and recovered measurements can be compared side by side:

  write         POST /telemetry                 keep-alive connection (every 5th one raises an alert)
  read_latest   GET  /machines/{id}             keep-alive connection
  read_history  GET  /machines/{id}/readings    keep-alive connection, larger response (~200 readings)
  newconn_read  GET  /machines/{id}             NEW TCP+TLS connection per request

Each request is logged with total latency and the server-reported application
and datastore time, so network time = total - application time.
"""
import argparse
import csv
import json
import os
import random
import statistics
import time

from common import alert_reading, new_client, normal_reading, timed_request

HISTORY_COUNT = 200
MACHINES = [f"B{i:02d}" for i in range(1, 6)]     # benchmark machines, separate from the dataset's M01..M20
FIELDS = ["label", "op", "seq", "t_start", "status", "ok", "total_ms", "app_ms", "db_ms",
          "net_ms", "bytes", "rid", "error"]


def pct(values, p):
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--writes", type=int, default=100)
    ap.add_argument("--reads", type=int, default=100)
    ap.add_argument("--history", type=int, default=50)
    ap.add_argument("--newconn", type=int, default=30)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--timeout", type=float, default=10.0)
    a = ap.parse_args()

    rnd = random.Random(a.seed)
    rows = []
    t_begin = time.time()

    def record(op, seq, res):
        res.pop("_resp", None)
        rows.append({"label": a.label, "op": op, "seq": seq, **res})

    with new_client(a.timeout) as c:
        # warm-up (not measured): open the connection and make sure every benchmark
        # machine already holds >= HISTORY_COUNT readings, so the history read returns
        # the same amount of data in every run
        seed_rnd = random.Random(1)
        for m in MACHINES:
            resp = c.get(f"/machines/{m}/readings", params={"count": HISTORY_COUNT})
            have = resp.json()["count"] if resp.status_code == 200 else 0
            for _ in range(max(1, HISTORY_COUNT - have)):
                c.post("/telemetry", json=normal_reading(seed_rnd, m))

        for i in range(a.writes):
            m = MACHINES[i % len(MACHINES)]
            body = alert_reading(rnd, m) if i % 5 == 4 else normal_reading(rnd, m)
            body["ts"] = time.time()
            record("write", i, timed_request(c, "POST", "/telemetry", json=body))
        for i in range(a.reads):
            record("read_latest", i, timed_request(c, "GET", f"/machines/{MACHINES[i % len(MACHINES)]}"))
        for i in range(a.history):
            record("read_history", i, timed_request(
                c, "GET", f"/machines/{MACHINES[i % len(MACHINES)]}/readings", params={"count": HISTORY_COUNT}))

    for i in range(a.newconn):
        with new_client(a.timeout) as c1:      # fresh TCP + TLS handshake every time
            record("newconn_read", i, timed_request(c1, "GET", f"/machines/{MACHINES[i % len(MACHINES)]}"))

    elapsed = time.time() - t_begin
    os.makedirs(a.outdir, exist_ok=True)
    with open(os.path.join(a.outdir, f"{a.label}_bench.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    summary = {"label": a.label, "requests": len(rows), "elapsed_s": round(elapsed, 2),
               "errors": sum(1 for r in rows if not r["ok"]), "ops": {}}
    print(f"\n[{a.label}] {len(rows)} requests in {elapsed:.1f}s")
    print(f"{'operation':<14}{'n':>5}{'err':>5}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}{'app p50':>10}{'db p50':>9}{'net p50':>10}")
    for op in ("write", "read_latest", "read_history", "newconn_read"):
        sel = [r for r in rows if r["op"] == op]
        good = [r for r in sel if r["ok"]]
        tot = [r["total_ms"] for r in good]
        s = {"n": len(sel), "errors": len(sel) - len(good),
             "p50_ms": round(pct(tot, 50), 2), "p95_ms": round(pct(tot, 95), 2), "p99_ms": round(pct(tot, 99), 2),
             "mean_ms": round(statistics.fmean(tot), 2) if tot else float("nan"),
             "app_p50_ms": round(pct([r["app_ms"] for r in good], 50), 2),
             "db_p50_ms": round(pct([r["db_ms"] for r in good], 50), 2),
             "net_p50_ms": round(pct([r["net_ms"] for r in good], 50), 2),
             "kbytes_p50": round(pct([r["bytes"] for r in good], 50) / 1000, 1)}
        summary["ops"][op] = s
        print(f"{op:<14}{s['n']:>5}{s['errors']:>5}{s['p50_ms']:>10}{s['p95_ms']:>10}{s['p99_ms']:>10}"
              f"{s['app_p50_ms']:>10}{s['db_p50_ms']:>9}{s['net_p50_ms']:>10}")
    ok_reqs = len(rows) - summary["errors"]
    summary["success_rate_pct"] = round(100.0 * ok_reqs / len(rows), 2) if rows else 0
    summary["requests_per_s"] = round(ok_reqs / elapsed, 1) if elapsed else 0
    with open(os.path.join(a.outdir, f"{a.label}_bench_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)


if __name__ == "__main__":
    main()
