#!/usr/bin/env bash
# Module E - Network performance:
#   state 1  baseline   healthy, unimpaired network
#   state 2  congested  delay / loss / rate limit injected on the WAN link (tc netem, tbf)
#   then     recovered  impairment removed, same workload again
# The workload is identical in every run (client/bench.py, fixed seed).
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab
HERE="$LAB_ROOT/experiments"
OUT="$EVID_DIR/E_performance"; mkdir -p "$OUT"; rm -f "$OUT"/*

bash "$HERE/impair.sh" clear >/dev/null
bash "$HERE/measure.sh" baseline

if bash "$HERE/impair.sh" delay 50 10 >/dev/null; then
  bash "$HERE/measure.sh" delay
else
  echo "SKIPPED delay profile: netem is not available (see lab/preflight.sh)" | tee "$OUT/delay_SKIPPED.txt"
fi

bash "$HERE/impair.sh" loss 5 >/dev/null && bash "$HERE/measure.sh" loss
bash "$HERE/impair.sh" rate 2 >/dev/null && bash "$HERE/measure.sh" rate

bash "$HERE/impair.sh" clear >/dev/null
bash "$HERE/measure.sh" recovered

"$PY" "$HERE/make_report.py" --section performance
fix_owner
echo "Saved raw measurements in $OUT"
