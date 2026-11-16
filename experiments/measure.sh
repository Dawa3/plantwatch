#!/usr/bin/env bash
# One measurement run with a fixed, identical workload:
#   RTT (ping), TCP throughput (iperf3), application benchmark, alert delivery delay.
#   sudo experiments/measure.sh <label>
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab
LABEL="${1:?usage: measure.sh <label>}"
OUT="$EVID_DIR/E_performance"; mkdir -p "$OUT"

log_event "MEASURE_START $LABEL"
echo "[$LABEL] started $(now_iso)" | tee "$OUT/${LABEL}_meta.txt"
{ echo "--- qdisc pw-r1 r1-wan"; r1 tc qdisc show dev r1-wan; echo "--- qdisc pw-r2 r2-wan"; r2 tc qdisc show dev r2-wan
  r1 nft list table inet pw_impair 2>/dev/null; } >> "$OUT/${LABEL}_meta.txt"

echo "[$LABEL] RTT: 50 pings plant -> API"
plant ping -c 50 -i 0.2 -q "$API_IP" > "$OUT/${LABEL}_ping.txt" 2>&1
tail -n 2 "$OUT/${LABEL}_ping.txt"

echo "[$LABEL] throughput: iperf3 plant -> API, 5 s TCP"
plant iperf3 -c "$API_IP" -p "$IPERF_PORT" -t 5 -J > "$OUT/${LABEL}_iperf.json" 2>&1 || echo "  iperf3 reported an error (kept in the JSON)"

echo "[$LABEL] application benchmark + alert delivery"
ip netns exec "$NS_OPS" "$PY" "$LAB_ROOT/ops/alert_watch.py" --label "$LABEL" --out "$OUT/${LABEL}_alerts.csv" >/dev/null 2>&1 &
AW=$!
sleep 2
plant "$PY" "$LAB_ROOT/client/bench.py" --label "$LABEL" --outdir "$OUT"
sleep 2
kill -TERM $AW 2>/dev/null; wait $AW 2>/dev/null

{ echo "--- qdisc statistics after the run"; r1 tc -s qdisc show dev r1-wan; r2 tc -s qdisc show dev r2-wan
  r1 nft list counters table inet pw_impair 2>/dev/null; } >> "$OUT/${LABEL}_meta.txt"
log_event "MEASURE_END $LABEL"
fix_owner
