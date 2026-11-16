"""PlantWatch API - industrial IoT telemetry and predictive-maintenance alerts.

Runs in the service zone (10.14.2.10:8443, HTTPS) and stores everything in
Redis in the data zone (10.14.3.10:6379).

Redis data model
  machines              SET     all known machine ids
  machine:{id}          HASH    latest state of one machine (+ tool_wear_limit, readings counter)
  telemetry:{id}        STREAM  time-ordered readings of one machine (capped)
  alerts                STREAM  alert events for all machines (capped)
  alerts:acked          HASH    alert id -> acknowledgement time
  stats                 HASH    global counters
"""
import json
import logging
import os
import time
import uuid
from typing import Literal, Optional

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from app.rules import DEFAULT_TOOL_WEAR_LIMIT, evaluate

TELEMETRY_MAXLEN = 2000
ALERTS_MAXLEN = 5000
ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"

# ---------------------------------------------------------------- logging ---
log = logging.getLogger("plantwatch")
log.setLevel(logging.INFO)
_handler = logging.FileHandler(os.environ["LOG_FILE"]) if os.environ.get("LOG_FILE") else logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(message)s"))
log.addHandler(_handler)
log.propagate = False


def log_json(level: str, **fields):
    fields = {"ts": round(time.time(), 3),
              "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
              "level": level, **fields}
    log.info(json.dumps(fields, separators=(",", ":")))


# ------------------------------------------------------------------ redis ---
rds = redis.Redis(
    host=os.environ.get("REDIS_HOST", "10.14.3.10"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    password=os.environ.get("REDIS_PASSWORD") or None,
    decode_responses=True,
    socket_connect_timeout=1.0,   # fail fast when the data zone is unreachable
    socket_timeout=2.0,
    retry=Retry(NoBackoff(), 1),  # one immediate reconnect attempt, then report 503
)

app = FastAPI(title="PlantWatch API", version="1.0")


async def timed(request: Request, awaitable):
    """Await a Redis call and add its duration to this request's datastore time."""
    t0 = time.perf_counter()
    try:
        return await awaitable
    finally:
        request.state.db_ms += (time.perf_counter() - t0) * 1000.0


@app.middleware("http")
async def observe(request: Request, call_next):
    """Per-request id, timing headers and one JSON log line."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.db_ms = 0.0
    t0 = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
    except RedisError as exc:
        status = 503
        log_json("ERROR", rid=rid, event="datastore_unavailable", error=f"{type(exc).__name__}: {exc}")
        response = JSONResponse({"error": "datastore_unavailable",
                                 "detail": "the data zone did not answer"}, status_code=503)
    total_ms = (time.perf_counter() - t0) * 1000.0
    db_ms = request.state.db_ms
    response.headers["X-Request-Id"] = rid
    response.headers["X-App-Ms"] = f"{total_ms:.3f}"   # time spent inside the API (includes datastore)
    response.headers["X-Db-Ms"] = f"{db_ms:.3f}"       # time spent waiting for Redis
    log_json("ERROR" if status >= 500 else ("WARN" if status >= 400 else "INFO"),
             rid=rid, client=request.client.host if request.client else "-",
             method=request.method, path=request.url.path, status=status,
             app_ms=round(total_ms, 3), db_ms=round(db_ms, 3))
    return response


# ----------------------------------------------------------------- models ---
class Reading(BaseModel):
    machine_id: str = Field(pattern=ID_PATTERN)
    type: Literal["L", "M", "H"] = "M"
    air_temp_k: float = Field(gt=200, lt=400)
    process_temp_k: float = Field(gt=200, lt=450)
    rpm: float = Field(ge=0, le=10000)
    torque_nm: float = Field(ge=0, le=200)
    tool_wear_min: float = Field(ge=0, le=1000)
    ts: Optional[float] = Field(default=None, description="sensor timestamp (epoch seconds)")
    source: str = Field(default="live", max_length=32)


class MachineConfig(BaseModel):
    tool_wear_limit: float = Field(gt=0, le=1000)


# -------------------------------------------------------------- endpoints ---
@app.get("/health")
async def health(request: Request):
    """Liveness of the API plus reachability of Redis across the app->data segment."""
    try:
        t0 = time.perf_counter()
        await timed(request, rds.ping())
        return {"status": "ok", "redis": "up", "redis_ms": round((time.perf_counter() - t0) * 1000, 3)}
    except RedisError as exc:
        log_json("ERROR", event="health_redis_down", error=f"{type(exc).__name__}: {exc}")
        return JSONResponse({"status": "degraded", "redis": "down"}, status_code=503)


@app.post("/telemetry", status_code=201)
async def post_telemetry(reading: Reading, request: Request):
    """CREATE a reading, UPDATE the machine's latest state, raise alerts."""
    received = time.time()
    r = reading.model_dump()
    r["ts"] = r["ts"] or received
    mid = r["machine_id"]
    key = f"machine:{mid}"

    limit = await timed(request, rds.hget(key, "tool_wear_limit"))
    alerts = evaluate(r, float(limit) if limit else DEFAULT_TOOL_WEAR_LIMIT)

    fields = {k: r[k] for k in ("ts", "type", "air_temp_k", "process_temp_k", "rpm",
                                "torque_nm", "tool_wear_min", "source")}
    pipe = rds.pipeline(transaction=True)
    pipe.xadd(f"telemetry:{mid}", fields, maxlen=TELEMETRY_MAXLEN, approximate=True)
    pipe.sadd("machines", mid)
    pipe.hset(key, mapping={"machine_id": mid, "last_ts": r["ts"], "last_source": r["source"],
                            "status": "alert" if alerts else "ok",
                            **{k: r[k] for k in ("type", "air_temp_k", "process_temp_k", "rpm",
                                                 "torque_nm", "tool_wear_min")}})
    pipe.hincrby(key, "readings", 1)
    pipe.hincrby("stats", "readings_total", 1)
    for a in alerts:
        pipe.xadd("alerts", {"machine_id": mid, "rule": a["rule"], "detail": a["detail"],
                             "sensor_ts": r["ts"], "received_ts": received, "source": "rule"},
                  maxlen=ALERTS_MAXLEN, approximate=True)
        pipe.hincrby("stats", "alerts_total", 1)
    res = await timed(request, pipe.execute())

    alert_ids = [res[5 + 2 * i] for i in range(len(alerts))]
    for a, aid in zip(alerts, alert_ids):
        a["id"] = aid
        log_json("WARN", event="alert", machine_id=mid, rule=a["rule"], alert_id=aid)
    return {"stored": True, "machine_id": mid, "stream_id": res[0], "alerts": alerts}


@app.get("/machines")
async def list_machines(request: Request):
    ids = sorted(await timed(request, rds.smembers("machines")))
    return {"count": len(ids), "machines": ids}


@app.get("/machines/{machine_id}")
async def get_machine(machine_id: str, request: Request):
    """READ the latest state of one machine."""
    state = await timed(request, rds.hgetall(f"machine:{machine_id}"))
    if not state:
        raise HTTPException(status_code=404, detail=f"unknown machine '{machine_id}'")
    return state


@app.get("/machines/{machine_id}/readings")
async def get_readings(machine_id: str, request: Request, count: int = Query(50, ge=1, le=1000)):
    """READ the most recent readings of one machine (newest first)."""
    if not await timed(request, rds.sismember("machines", machine_id)):
        raise HTTPException(status_code=404, detail=f"unknown machine '{machine_id}'")
    rows = await timed(request, rds.xrevrange(f"telemetry:{machine_id}", count=count))
    return {"machine_id": machine_id, "count": len(rows),
            "readings": [{"id": sid, **f} for sid, f in rows]}


@app.put("/machines/{machine_id}/config")
async def put_config(machine_id: str, cfg: MachineConfig, request: Request):
    """UPDATE the tool-wear alert threshold of one machine."""
    if not await timed(request, rds.sismember("machines", machine_id)):
        raise HTTPException(status_code=404, detail=f"unknown machine '{machine_id}'")
    await timed(request, rds.hset(f"machine:{machine_id}", "tool_wear_limit", cfg.tool_wear_limit))
    return {"machine_id": machine_id, "tool_wear_limit": cfg.tool_wear_limit}


@app.get("/alerts")
async def get_alerts(request: Request, count: int = Query(50, ge=1, le=1000),
                     after: Optional[str] = Query(None, pattern=r"^\d+-\d+$")):
    """READ alerts. Without `after`: newest first. With `after=<id>`: alerts newer than that id, oldest first."""
    if after:
        rows = await timed(request, rds.xrange("alerts", min=f"({after}", count=count))
    else:
        rows = await timed(request, rds.xrevrange("alerts", count=count))
    acked = await timed(request, rds.hmget("alerts:acked", [sid for sid, _ in rows])) if rows else []
    return {"count": len(rows),
            "alerts": [{"id": sid, **f, "acked": bool(a)} for (sid, f), a in zip(rows, acked)]}


@app.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str, request: Request):
    """UPDATE: acknowledge an alert."""
    if not await timed(request, rds.xrange("alerts", min=alert_id, max=alert_id)):
        raise HTTPException(status_code=404, detail=f"unknown alert '{alert_id}'")
    await timed(request, rds.hset("alerts:acked", alert_id, time.time()))
    return {"id": alert_id, "acked": True}


@app.get("/stats")
async def stats(request: Request):
    s = await timed(request, rds.hgetall("stats"))
    machines = await timed(request, rds.scard("machines"))
    alerts = await timed(request, rds.xlen("alerts"))
    return {"machines": machines, "alerts_in_stream": alerts, **s}
