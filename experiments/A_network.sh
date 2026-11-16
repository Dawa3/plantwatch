#!/usr/bin/env bash
# Module A - Network infrastructure evidence:
# addresses, route tables, forwarding, ping matrix, traceroute.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab
OUT="$EVID_DIR/A_network"; mkdir -p "$OUT"

{
header "Module A: network infrastructure"

section "Interfaces and addresses per zone"
for ns in $ALL_NS; do echo "--- $ns"; ip -n "$ns" -br addr show | grep -v '^lo'; done

section "Route tables"
for ns in $ALL_NS; do echo "--- $ns"; ip -n "$ns" route show; done

section "IPv4 forwarding (routers only)"
for ns in $ALL_NS; do printf '%-10s net.ipv4.ip_forward = %s\n' "$ns" "$(in_ns "$ns" sysctl -n net.ipv4.ip_forward)"; done

section "Path: plant -> API (traceroute, ICMP)"
run plant traceroute -n -I -q 1 "$API_IP"
section "Path: ops -> API"
run ops traceroute -n -I -q 1 "$API_IP"
section "Path: API -> Redis (one router hop inside the data centre)"
run api traceroute -n -T -p "$REDIS_PORT" -q 1 "$DB_IP"

section "Reachability: RTT plant -> API"
run plant ping -c 10 -i 0.2 -q "$API_IP"

section "Connectivity matrix (intended reachability and intended boundaries)"
expect_ok   "plant -> edge router        $R1_PLANT_IP"  plant ping -c 1 -W 1 "$R1_PLANT_IP"
expect_ok   "plant -> dc router (wan)    $R2_WAN_IP"    plant ping -c 1 -W 1 "$R2_WAN_IP"
expect_ok   "plant -> API                $API_IP"       plant ping -c 1 -W 1 "$API_IP"
expect_ok   "ops   -> API                $API_IP"       ops   ping -c 1 -W 1 "$API_IP"
expect_ok   "ops   -> Redis host (ICMP only) $DB_IP"    ops   ping -c 1 -W 1 "$DB_IP"
expect_ok   "API   -> Redis tcp/6379     $DB_IP"        api   nc -z -w 2 "$DB_IP" "$REDIS_PORT"
expect_fail "API   -> plant host (data centre may not initiate)" api ping -c 1 -W 1 "$PLANT_IP"
expect_fail "plant -> Redis host         $DB_IP"        plant ping -c 1 -W 1 "$DB_IP"
expect_fail "plant -> ops zone           $OPS_IP"       plant ping -c 1 -W 1 "$OPS_IP"

section "Neighbour (ARP) tables on the routers"
echo "--- $NS_R1"; ip -n "$NS_R1" neigh show
echo "--- $NS_R2"; ip -n "$NS_R2" neigh show
summary
} 2>&1 | tee "$OUT/connectivity.txt"
rc=${PIPESTATUS[0]}
fix_owner
echo "Saved: $OUT/connectivity.txt"
exit "$rc"
