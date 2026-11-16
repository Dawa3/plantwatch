#!/usr/bin/env python3
"""Alert consumer, run from the operations zone.

Polls GET /alerts?after=<last id> and records when each new alert first
becomes visible to an operator. For every alert:

  uplink_ms    = API receive time - sensor timestamp     (plant -> API)
  delivery_ms  = time seen by ops  - sensor timestamp    (plant -> API -> Redis -> ops)

All zones run on one host and share one clock, so the differences are exact.
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
    ap.add_argument("--label", default="")
    ap.add_argument("--interval", type=float, default=0.2)
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="") as fh, httpx.Client(base_url=API_URL, verify=CA_CERT, timeout=10, trust_env=False) as c:
        w = csv.writer(fh)
        w.writerow(["label", "alert_id", "machine_id", "rule", "sensor_ts", "received_ts", "seen_ts",
                    "uplink_ms", "delivery_ms"])
        last = None
        while running and last is None:                 # find the current end of the alert stream
            try:
                newest = c.get("/alerts", params={"count": 1}).json()["alerts"]
                last = newest[0]["id"] if newest else "0-0"
            except (httpx.HTTPError, KeyError, ValueError):
                time.sleep(a.interval)
        print("READY", flush=True)
        while running:
            try:
                alerts = c.get("/alerts", params={"after": last, "count": 200}).json()["alerts"]
                seen = time.time()
                for al in alerts:
                    last = al["id"]
                    sensor, received = float(al["sensor_ts"]), float(al["received_ts"])
                    w.writerow([a.label, al["id"], al["machine_id"], al["rule"], f"{sensor:.4f}",
                                f"{received:.4f}", f"{seen:.4f}",
                                f"{(received - sensor) * 1000:.2f}", f"{(seen - sensor) * 1000:.2f}"])
                fh.flush()
            except (httpx.HTTPError, KeyError, ValueError):
                pass
            time.sleep(a.interval)


if __name__ == "__main__":
    main()
