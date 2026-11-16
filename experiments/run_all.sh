#!/usr/bin/env bash
# Run every module's evidence script in order, then build the results report.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab
HERE="$LAB_ROOT/experiments"

for step in validate A_network B_service C_security D_observability E_performance F_recovery; do
  printf '\n\n########## %s ##########\n' "$step"
  bash "$HERE/$step.sh" || echo "!! $step reported a problem - check its output above"
done
"$PY" "$HERE/make_report.py"
fix_owner
echo
echo "All evidence is in $EVID_DIR  (summary: evidence/results.md)"
