#!/usr/bin/env bash
# Module F - Automation and recovery (experimental state 3: failure + recovery).
#
# Three controlled faults are injected one after another while a health probe
# (ops/monitor.py) records availability and the watchdog (ops/watchdog.sh)
# detects, diagnoses and repairs each one:
#   1. API process crash          (service failure)
#   2. Redis process crash        (datastore failure; data must survive)
#   3. WAN link down              (network failure; static routes are lost with the link)
# Before and after every fault the SAME client transaction is executed.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab
OUT="$EVID_DIR/F_recovery"; mkdir -p "$OUT"; rm -f "$OUT"/*
bash "$LAB_ROOT/experiments/impair.sh" clear >/dev/null

ip netns exec "$NS_OPS" "$PY" "$LAB_ROOT/ops/monitor.py" --out "$OUT/monitor.csv" >/dev/null 2>&1 &
MON=$!
bash "$LAB_ROOT/ops/watchdog.sh" "$OUT/watchdog.log" >/dev/null 2>&1 &
WD=$!
cleanup() { kill -TERM $MON $WD 2>/dev/null; wait $MON $WD 2>/dev/null; net_repair; fix_owner; }
trap cleanup EXIT

roundtrip() { plant "$PY" "$LAB_ROOT/client/roundtrip.py" 2; }
stats()     { plant curl -s --noproxy '*' --cacert "$CA_CERT" -m 3 "$API_URL/stats"; echo; }
probe()     { plant curl -sS --noproxy '*' --cacert "$CA_CERT" -m 2 -w '\n[HTTP %{http_code}]\n' "$API_URL/health"; echo "[curl exit $?]"; }

fault() {  # fault <name> <description> <inject command...>
  local name="$1" desc="$2"; shift 2
  section "FAULT: $desc"
  echo "Before ($(now_iso)):"; roundtrip; stats
  log_event "FAULT_INJECT $name"
  echo "\$ $*"; "$@"
  sleep 1
  echo; echo "During the outage ($(now_iso)) - the same client transaction and a health probe:"
  roundtrip; probe
  echo; echo "Waiting for the watchdog to detect and repair ..."
  local t0; t0=$(date +%s)
  if wait_healthy 60; then
    log_event "SERVICE_RESTORED $name"
    echo "Health check is 200 again after ~$(( $(date +%s) - t0 + 1 )) s"
  else
    log_event "RESTORE_FAILED $name"; echo "NOT RESTORED within 60 s"
  fi
  echo; echo "After recovery ($(now_iso)):"; roundtrip; stats
  sleep 6      # steady period between faults
}

{
header "Module F: automation and recovery"
log_event "F_RECOVERY_START"
sleep 6        # healthy period at the start of the timeline

fault api_crash   "API process killed (kill -9)"               stop_api -9
fault redis_crash "Redis process killed (kill -9)"             stop_redis -9
fault wan_down    "WAN link pw-r1 <-> pw-r2 administratively down" ip -n "$NS_R1" link set r1-wan down

log_event "F_RECOVERY_END"
kill -TERM $MON $WD 2>/dev/null; wait $MON $WD 2>/dev/null

section "Watchdog log (detection, diagnosis, action, recovery)"
cat "$OUT/watchdog.log"

section "API log: errors recorded during the experiment"
grep '"level":"ERROR"' "$LOG_DIR/api.log" | tail -n 8

section "Redis log: restart and data reload from the append-only file"
grep -E "Ready to accept|DB loaded|Loading|AOF" "$LOG_DIR/redis.log" | tail -n 6

section "Outage summary computed from the health-probe record"
"$PY" "$LAB_ROOT/experiments/make_report.py" --section recovery
} 2>&1 | tee "$OUT/recovery.txt"
echo "Saved: $OUT/recovery.txt, monitor.csv, watchdog.log"
