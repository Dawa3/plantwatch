#!/usr/bin/env python3
"""Send exactly one traced transaction and print client-side timestamps.

Used by the observability experiment: the printed request id and timestamps
are matched against packet captures and the API log.
"""
import json
import time

from common import new_client, timed_request


def stamp(t):
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t * 1e6) % 1000000:06d}"


def main():
    body = {"machine_id": "TRACE01", "type": "H", "air_temp_k": 298.4, "process_temp_k": 308.9,
            "rpm": 1551, "torque_nm": 42.8, "tool_wear_min": 77, "ts": time.time(), "source": "trace"}
    t0 = time.time()
    with new_client() as c:                       # new TCP connection + TLS handshake
        w = timed_request(c, "POST", "/telemetry", json=body)
        t1 = time.time()
        r = timed_request(c, "GET", "/machines/TRACE01")
        t2 = time.time()
    out = {
        "client_connect_start": stamp(t0), "client_connect_start_epoch": round(t0, 6),
        "write": {"request_id": w["rid"], "status": w["status"], "done": stamp(t1),
                  "total_ms": w["total_ms"], "app_ms": w["app_ms"], "db_ms": w["db_ms"], "net_ms": w["net_ms"]},
        "read": {"request_id": r["rid"], "status": r["status"], "done": stamp(t2),
                 "total_ms": r["total_ms"], "app_ms": r["app_ms"], "db_ms": r["db_ms"], "net_ms": r["net_ms"]},
        "stored_state": r["_resp"].json() if r["_resp"] is not None else None,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
