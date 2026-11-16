#!/usr/bin/env python3
"""Health probe, run from the operations zone.

Every interval it opens a NEW HTTPS connection to GET /health and appends one
row to a CSV: timestamp, ok flag, HTTP status, latency, error. Availability,
outage duration and recovery time are computed from this file.

    sudo ip netns exec pw-ops .venv/bin/python ops/monitor.py --out evidence/F_recovery/monitor.csv
"""
import argparse
import csv
import os
import signal
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "client"))
from common import API_URL, CA_CERT  # noqa: E402

running = True


def stop(*_):
    global running
    running = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--timeout", type=float, default=1.5)
    ap.add_argument("--duration", type=float, default=0, help="seconds (0 = until SIGTERM)")
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    t_end = time.time() + a.duration if a.duration else None
    with open(a.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["epoch", "iso", "ok", "status", "latency_ms", "error"])
        nxt = time.time()
        while running and (t_end is None or time.time() < t_end):
            t_wall = time.time()
            t0 = time.perf_counter()
            status, err = 0, ""
            try:
                with httpx.Client(verify=CA_CERT, timeout=a.timeout, trust_env=False) as c:
                    status = c.get(API_URL + "/health").status_code
            except httpx.HTTPError as exc:
                err = type(exc).__name__
            lat = (time.perf_counter() - t0) * 1000.0
            w.writerow([f"{t_wall:.3f}", time.strftime("%H:%M:%S", time.localtime(t_wall)) + f".{int(t_wall * 1000) % 1000:03d}",
                        int(status == 200), status, f"{lat:.2f}", err])
            fh.flush()
            nxt += a.interval
            time.sleep(max(0.0, nxt - time.time()))


if __name__ == "__main__":
    main()
