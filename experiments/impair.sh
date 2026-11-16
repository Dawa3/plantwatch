#!/usr/bin/env bash
# Controlled network impairment on the WAN link between pw-r1 and pw-r2.
# Applied to the egress of BOTH routers, so each direction is affected.
#
#   sudo experiments/impair.sh delay [ms=50] [jitter_ms=10]   # +2x ms of RTT
#   sudo experiments/impair.sh loss  [percent=5]
#   sudo experiments/impair.sh rate  [mbit=2]
#   sudo experiments/impair.sh combo [ms=50] [percent=2] [mbit=2]
#   sudo experiments/impair.sh clear
#   sudo experiments/impair.sh show
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab

each_wan() { r1 "$@" dev r1-wan "${EXTRA[@]}"; local a=$?; r2 "$@" dev r2-wan "${EXTRA[@]}"; local b=$?; return $((a|b)); }
tcq() { EXTRA=("$@"); each_wan tc qdisc replace; }

has_netem() {
  modprobe sch_netem 2>/dev/null
  r1 tc qdisc replace dev r1-wan root netem delay 0ms 2>/dev/null || return 1
  r1 tc qdisc del dev r1-wan root 2>/dev/null; return 0
}

clear_all() {
  r1 tc qdisc del dev r1-wan root 2>/dev/null
  r2 tc qdisc del dev r2-wan root 2>/dev/null
  r1 nft delete table inet pw_impair 2>/dev/null
  return 0
}

nft_loss() {  # fallback when netem is unavailable: random drop in the forwarding path
  local permille; permille="$(awk -v p="$1" 'BEGIN{printf "%d", p*10}')"
  r1 nft -f - <<EOF
table inet pw_impair {
    counter dropped { }
    chain forward {
        type filter hook forward priority -10; policy accept;
        iifname "r1-wan" numgen random mod 1000 < $permille counter name dropped drop
        oifname "r1-wan" numgen random mod 1000 < $permille counter name dropped drop
    }
}
EOF
}

cmd="${1:-show}"
case "$cmd" in
  delay)
    ms="${2:-50}"; jit="${3:-10}"
    clear_all
    has_netem || { echo "netem is not available in this kernel (see lab/preflight.sh)."; exit 2; }
    tcq root netem delay "${ms}ms" "${jit}ms" || exit 1
    log_event "IMPAIR delay ${ms}ms +-${jit}ms per direction (netem) on wan link" ;;
  loss)
    pct="${2:-5}"
    clear_all
    if has_netem; then
      tcq root netem loss "${pct}%" || exit 1
      log_event "IMPAIR loss ${pct}% per direction (netem) on wan link"
    else
      nft_loss "$pct" || exit 1
      log_event "IMPAIR loss ${pct}% per direction (nftables random drop; netem unavailable) on wan link"
    fi ;;
  rate)
    mbit="${2:-2}"
    clear_all
    tcq root tbf rate "${mbit}mbit" burst 32kbit latency 50ms || exit 1
    log_event "IMPAIR rate ${mbit}mbit per direction (tbf) on wan link" ;;
  combo)
    ms="${2:-50}"; pct="${3:-2}"; mbit="${4:-2}"
    clear_all
    has_netem || { echo "netem is not available in this kernel (see lab/preflight.sh)."; exit 2; }
    tcq root handle 1: netem delay "${ms}ms" loss "${pct}%" || exit 1
    tcq parent 1:1 handle 10: tbf rate "${mbit}mbit" burst 32kbit latency 50ms || exit 1
    log_event "IMPAIR combo delay ${ms}ms loss ${pct}% rate ${mbit}mbit per direction on wan link" ;;
  clear)
    clear_all
    log_event "IMPAIR cleared - wan link back to normal" ;;
  show) ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac

echo "--- pw-r1 r1-wan"; r1 tc -s qdisc show dev r1-wan
echo "--- pw-r2 r2-wan"; r2 tc -s qdisc show dev r2-wan
r1 nft list table inet pw_impair 2>/dev/null
exit 0
