#!/usr/bin/env bash
# Tear the lab down: stop services, delete namespaces. Data in run/redis is kept.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/services.sh"
need_root "$@"

pkill -f "^(sudo |/bin/|/usr/bin/)*bash [^ ]*ops/watchdog\.sh" 2>/dev/null || true
pkill -f "^[^ ]*python[^ ]* [^ ]*ops/monitor\.py" 2>/dev/null || true
pkill -f "^[^ ]*python[^ ]* [^ ]*ops/alert_watch\.py" 2>/dev/null || true
stop_api
stop_redis
stop_iperf

for ns in $ALL_NS; do
  if [ -e "/var/run/netns/$ns" ]; then
    # Kill anything still running inside the namespace, then remove it.
    for p in $(ip netns pids "$ns" 2>/dev/null); do kill -9 "$p" 2>/dev/null || true; done
    ip netns del "$ns"
  fi
  rm -rf "/etc/netns/$ns"
done
fix_owner
echo "Lab is down."
