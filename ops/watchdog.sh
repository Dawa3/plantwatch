#!/usr/bin/env bash
# Automated detection and recovery.
#
# Probes GET /health from the operations zone once per second. After THRESHOLD
# consecutive failures it diagnoses the cause (WAN link/routes, Redis, API) and
# runs the matching recovery action, then confirms the service is healthy again.
#
#   sudo ops/watchdog.sh [logfile]
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lab/services.sh"
need_root "$@"

LOG="${1:-$EVID_DIR/F_recovery/watchdog.log}"
THRESHOLD="${THRESHOLD:-3}"
INTERVAL="${INTERVAL:-1}"
mkdir -p "$(dirname "$LOG")"

wlog() { printf '%s\t%s\t%s\n' "$(now_epoch)" "$(now_iso)" "$*" | tee -a "$LOG"; }

recover() {
  local acted=0
  if ! wan_link_ok; then
    wlog "DIAGNOSIS wan link down or static routes missing"
    wlog "ACTION net_repair: link up + re-add static routes on pw-r1/pw-r2"
    net_repair; acted=1
  fi
  if ! pid_alive "$RUN_DIR/redis.pid"; then
    wlog "DIAGNOSIS redis process not running"
    wlog "ACTION start_redis (data restored from append-only file)"
    start_redis; acted=1
  fi
  if ! pid_alive "$RUN_DIR/api.pid"; then
    wlog "DIAGNOSIS api process not running"
    wlog "ACTION start_api"
    start_api; acted=1
  fi
  if [ $acted = 0 ]; then
    wlog "DIAGNOSIS processes and link look fine but probes fail"
    wlog "ACTION restart api"
    stop_api; start_api
  fi
}

wlog "WATCHDOG_START threshold=$THRESHOLD interval=${INTERVAL}s"
fails=0
first_fail=""
trap 'wlog "WATCHDOG_STOP"; exit 0' TERM INT
while true; do
  code="$(health_code 1)"
  if [ "$code" = "200" ]; then
    fails=0
  else
    fails=$((fails + 1))
    [ $fails = 1 ] && first_fail="$(now_epoch)"
    wlog "PROBE_FAIL http=$code consecutive=$fails"
    if [ $fails -ge "$THRESHOLD" ]; then
      wlog "DETECTED outage after $fails failed probes"
      recover
      if wait_healthy 30; then
        wlog "RECOVERED health=200 outage_s=$(awk -v a="$(now_epoch)" -v b="$first_fail" 'BEGIN{printf "%.1f", a - b}')"
      else
        wlog "RECOVERY_FAILED still unhealthy after 30s"
      fi
      fails=0
    fi
  fi
  sleep "$INTERVAL"
done
