#!/usr/bin/env bash
# Start / stop / inspect the lab services. Sourced by other scripts, or run as:
#   sudo lab/services.sh start|stop|status [redis|api|iperf|all]
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"

pid_alive() { [ -f "$1" ] && kill -0 "$(cat "$1" 2>/dev/null)" 2>/dev/null; }

# ---- Redis (data zone) -----------------------------------------------------
start_redis() {
  pid_alive "$RUN_DIR/redis.pid" && return 0
  mkdir -p "$RUN_DIR/redis" "$LOG_DIR"
  : "${REDIS_PASSWORD:?REDIS_PASSWORD missing - run: make setup}"
  sed -e "s|@BIND@|$DB_IP|" -e "s|@PASSWORD@|$REDIS_PASSWORD|" \
      -e "s|@RUN@|$RUN_DIR|g" -e "s|@LOGS@|$LOG_DIR|" \
      "$LAB_ROOT/lab/redis.conf.tmpl" > "$RUN_DIR/redis.conf"
  chmod 600 "$RUN_DIR/redis.conf"
  rm -f "$RUN_DIR/redis.pid"
  in_ns "$NS_DB" redis-server "$RUN_DIR/redis.conf"
  for _ in $(seq 1 50); do
    in_ns "$NS_DB" env REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -h "$DB_IP" ping 2>/dev/null | grep -q PONG && return 0
    sleep 0.1
  done
  echo "Redis did not start; see $LOG_DIR/redis.log" >&2; return 1
}

stop_redis() {  # stop_redis [-9]
  local sig="${1:--TERM}"
  if pid_alive "$RUN_DIR/redis.pid"; then kill "$sig" "$(cat "$RUN_DIR/redis.pid")" 2>/dev/null; fi
  pkill "$sig" -f "redis-server $DB_IP:$REDIS_PORT" 2>/dev/null || true
  sleep 0.3
}

# ---- API (service zone) ----------------------------------------------------
start_api() {
  pid_alive "$RUN_DIR/api.pid" && return 0
  mkdir -p "$LOG_DIR"
  : "${REDIS_PASSWORD:?REDIS_PASSWORD missing - run: make setup}"
  # call ip directly (not the in_ns function) so that $! is the server's own pid
  ip netns exec "$NS_API" env \
      REDIS_HOST="$DB_IP" REDIS_PORT="$REDIS_PORT" REDIS_PASSWORD="$REDIS_PASSWORD" \
      LOG_FILE="$LOG_DIR/api.log" \
    nohup "$PY" -m uvicorn app.main:app --app-dir "$LAB_ROOT" \
      --host "$API_IP" --port "$API_PORT" \
      --ssl-keyfile "$CERT_DIR/api.key" --ssl-certfile "$CERT_DIR/api.pem" \
      --no-access-log --log-level warning >> "$LOG_DIR/api.out" 2>&1 &
  echo $! > "$RUN_DIR/api.pid"
}

stop_api() {  # stop_api [-9]
  local sig="${1:--TERM}"
  if pid_alive "$RUN_DIR/api.pid"; then kill "$sig" "$(cat "$RUN_DIR/api.pid")" 2>/dev/null; fi
  pkill "$sig" -f "uvicorn app.main:app --app-dir $LAB_ROOT" 2>/dev/null || true
  rm -f "$RUN_DIR/api.pid"
  sleep 0.3
}

# ---- iperf3 server (on the API host, for throughput tests) -----------------
start_iperf() {
  pid_alive "$RUN_DIR/iperf.pid" && return 0
  in_ns "$NS_API" iperf3 -s -B "$API_IP" -p "$IPERF_PORT" -D --pidfile "$RUN_DIR/iperf.pid" >/dev/null 2>&1 || true
}
stop_iperf() {
  pid_alive "$RUN_DIR/iperf.pid" && kill "$(cat "$RUN_DIR/iperf.pid")" 2>/dev/null
  rm -f "$RUN_DIR/iperf.pid"
}

# ---- health ----------------------------------------------------------------
# HTTP status of GET /health as seen from the operations zone ("000" = no answer).
health_code() {
  in_ns "$NS_OPS" curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --cacert "$CA_CERT" \
    --max-time "${1:-2}" "$API_URL/health" 2>/dev/null || true
}

wait_healthy() {  # wait_healthy [seconds]
  local deadline=$(( $(date +%s) + ${1:-30} ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    [ "$(health_code)" = "200" ] && return 0
    sleep 0.3
  done
  return 1
}

# Re-assert link state and static routes on both routers (used by recovery).
net_repair() {
  ip -n "$NS_R1" link set r1-wan up
  ip -n "$NS_R2" link set r2-wan up
  ip -n "$NS_R1" route replace "$NET_APP"   via "$R2_WAN_IP"
  ip -n "$NS_R1" route replace "$NET_DATA"  via "$R2_WAN_IP"
  ip -n "$NS_R2" route replace "$NET_PLANT" via "$R1_WAN_IP"
  ip -n "$NS_R2" route replace "$NET_OPS"   via "$R1_WAN_IP"
}

wan_link_ok() {
  ip -n "$NS_R1" -o link show r1-wan | grep -q "LOWER_UP" || return 1
  ip -n "$NS_R1" route show "$NET_APP" | grep -q "via $R2_WAN_IP" || return 1
  ip -n "$NS_R2" route show "$NET_PLANT" | grep -q "via $R1_WAN_IP" || return 1
}

services_status() {
  printf '%-8s %s\n' "redis" "$(pid_alive "$RUN_DIR/redis.pid" && echo "running (pid $(cat "$RUN_DIR/redis.pid"))" || echo stopped)"
  printf '%-8s %s\n' "api"   "$(pid_alive "$RUN_DIR/api.pid"   && echo "running (pid $(cat "$RUN_DIR/api.pid"))"   || echo stopped)"
  printf '%-8s %s\n' "iperf" "$(pid_alive "$RUN_DIR/iperf.pid" && echo "running (pid $(cat "$RUN_DIR/iperf.pid"))" || echo stopped)"
  printf '%-8s %s\n' "wan"   "$(wan_link_ok && echo up || echo DOWN)"
  printf '%-8s %s\n' "health" "HTTP $(health_code)"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  need_root "$@"
  what="${2:-all}"
  case "${1:-status}" in
    start)  case "$what" in redis) start_redis;; api) start_api;; iperf) start_iperf;; all) start_redis; start_api; start_iperf;; esac ;;
    stop)   case "$what" in redis) stop_redis;;  api) stop_api;;  iperf) stop_iperf;;  all) stop_api; stop_redis; stop_iperf;; esac ;;
    status) services_status ;;
    *) echo "usage: $0 start|stop|status [redis|api|iperf|all]"; exit 1 ;;
  esac
fi
