"""Shared helpers for the PlantWatch client-side tools."""
import os
import random
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_URL = os.environ.get("API_URL", "https://api.plantwatch.lab:8443")
CA_CERT = os.environ.get("CA_CERT", os.path.join(ROOT, "run", "certs", "ca.pem"))


def new_client(timeout: float = 10.0) -> httpx.Client:
    """HTTPS client that trusts only the lab CA (server certificate is verified)."""
    return httpx.Client(base_url=API_URL, verify=CA_CERT, timeout=timeout, trust_env=False)


def normal_reading(rnd: random.Random, machine_id: str) -> dict:
    """A reading that violates none of the alert rules."""
    air = round(rnd.uniform(297.0, 303.0), 1)
    return {"machine_id": machine_id, "type": rnd.choice("LMH"),
            "air_temp_k": air, "process_temp_k": round(air + rnd.uniform(9.5, 11.0), 1),
            "rpm": rnd.randint(1400, 1600), "torque_nm": round(rnd.uniform(30.0, 50.0), 1),
            "tool_wear_min": rnd.randint(0, 150), "source": "bench"}


def alert_reading(rnd: random.Random, machine_id: str) -> dict:
    """A reading with worn tooling: triggers exactly the TWF rule."""
    r = normal_reading(rnd, machine_id)
    r.update(tool_wear_min=230, torque_nm=40.0, rpm=1500)
    return r


def timed_request(client: httpx.Client, method: str, path: str, **kw) -> dict:
    """Send one request and split its latency into network / application / datastore time."""
    t_wall = time.time()
    t0 = time.perf_counter()
    try:
        resp = client.request(method, path, **kw)
        total = (time.perf_counter() - t0) * 1000.0
        app_ms = float(resp.headers.get("x-app-ms", "nan"))
        db_ms = float(resp.headers.get("x-db-ms", "nan"))
        return {"t_start": round(t_wall, 4), "status": resp.status_code, "ok": int(resp.status_code < 400),
                "total_ms": round(total, 3), "app_ms": round(app_ms, 3), "db_ms": round(db_ms, 3),
                "net_ms": round(total - app_ms, 3), "bytes": len(resp.content),
                "rid": resp.headers.get("x-request-id", ""), "error": "", "_resp": resp}
    except httpx.HTTPError as exc:
        total = (time.perf_counter() - t0) * 1000.0
        return {"t_start": round(t_wall, 4), "status": 0, "ok": 0, "total_ms": round(total, 3),
                "app_ms": "", "db_ms": "", "net_ms": "", "bytes": 0, "rid": "",
                "error": type(exc).__name__, "_resp": None}
