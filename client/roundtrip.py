#!/usr/bin/env python3
"""One end-to-end transaction used as the standard health proof:
write a reading with a unique value, read it back, compare.

Exit code 0 = PASS. Run from the plant zone:
    sudo ip netns exec pw-plant .venv/bin/python client/roundtrip.py
"""
import sys
import time

from common import new_client, timed_request


def main():
    marker = round(int(time.time() * 1000) % 100000 / 100.0 + 1000, 2)      # unique rpm value, e.g. 1437.21
    body = {"machine_id": "CHK01", "type": "M", "air_temp_k": 300.0, "process_temp_k": 310.0,
            "rpm": marker, "torque_nm": 40.0, "tool_wear_min": 10, "ts": time.time(), "source": "roundtrip"}
    try:
        with new_client(timeout=float(sys.argv[1]) if len(sys.argv) > 1 else 5.0) as c:
            w = timed_request(c, "POST", "/telemetry", json=body)
            if w["status"] != 201:
                print(f"FAIL write  status={w['status']} error={w['error']} total={w['total_ms']}ms")
                return 1
            r = timed_request(c, "GET", "/machines/CHK01")
            got = float(r["_resp"].json().get("rpm", -1)) if r["status"] == 200 else None
    except Exception as exc:                       # connection refused, timeout, TLS failure ...
        print(f"FAIL {type(exc).__name__}: {exc}")
        return 1
    if got is None or abs(got - marker) > 1e-6:
        print(f"FAIL read   status={r['status']} expected rpm={marker} got={got}")
        return 1
    print(f"PASS client->API->Redis round trip  rid={w['rid']}  "
          f"write {w['total_ms']}ms (app {w['app_ms']} / db {w['db_ms']})  "
          f"read {r['total_ms']}ms  value={got}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
