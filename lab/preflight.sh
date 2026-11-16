#!/usr/bin/env bash
# Check that this kernel has what the lab needs (important on WSL2).
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
need_root "$@"

ok=1
say() { printf '  %-34s %s\n' "$1" "$2"; }

echo "Kernel: $(uname -r)"
for t in ip nft tc tcpdump redis-server redis-cli iperf3 curl openssl ping traceroute nc ethtool; do
  if command -v "$t" >/dev/null; then say "tool: $t" ok; else say "tool: $t" "MISSING (run: make setup)"; ok=0; fi
done

T=pw-preflight
ip netns del $T 2>/dev/null
if ip netns add $T 2>/dev/null; then say "network namespaces" ok; else say "network namespaces" FAIL; ok=0; fi
ip -n $T link set lo up 2>/dev/null

if ip -n $T link add v0 type veth peer name v1 2>/dev/null; then say "veth pairs" ok; else say "veth pairs" FAIL; ok=0; fi
if ip netns exec $T nft add table inet t 2>/dev/null; then say "nftables" ok; else say "nftables" FAIL; ok=0; fi

modprobe sch_netem 2>/dev/null
if ip netns exec $T tc qdisc add dev lo root netem delay 1ms 2>/dev/null; then
  say "tc netem (delay/loss)" ok
  ip netns exec $T tc qdisc del dev lo root 2>/dev/null
else
  say "tc netem (delay/loss)" "NOT AVAILABLE"
  NETEM_MISSING=1
fi
modprobe sch_tbf 2>/dev/null
if ip netns exec $T tc qdisc add dev lo root tbf rate 1mbit burst 32kbit latency 100ms 2>/dev/null; then
  say "tc tbf (rate limit)" ok
else
  say "tc tbf (rate limit)" "NOT AVAILABLE"
fi
ip netns del $T 2>/dev/null

if [ "${NETEM_MISSING:-0}" = 1 ]; then
  cat <<'EOF'

  netem is missing from this kernel. On WSL2, update the kernel from Windows
  PowerShell and restart WSL, then re-run this check:

      wsl --update
      wsl --shutdown

  If it is still missing, the lab still runs: packet loss falls back to an
  nftables random-drop rule and rate limiting uses tbf, but the *delay*
  experiment needs netem (run that one on a regular Linux VM or lab machine).
EOF
fi

[ $ok = 1 ] && echo "Preflight passed." || { echo "Preflight found problems."; exit 1; }
