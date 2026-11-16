#!/usr/bin/env bash
# Automated configuration validation / health check for the whole platform.
# Exit code 0 only if every check passes.   sudo make test
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab
OUT="$EVID_DIR/validate.txt"; mkdir -p "$EVID_DIR"

{
header "configuration validation"
echo
echo "Network"
for ns in $ALL_NS; do expect_ok "namespace $ns exists" ip netns pids "$ns"; done
expect_ok   "pw-r1 forwards IPv4"                    r1 sh -c '[ "$(sysctl -n net.ipv4.ip_forward)" = 1 ]'
expect_ok   "pw-r2 forwards IPv4"                    r2 sh -c '[ "$(sysctl -n net.ipv4.ip_forward)" = 1 ]'
expect_ok   "pw-r1 has static route to app segment"  sh -c "ip -n $NS_R1 route show $NET_APP | grep -q $R2_WAN_IP"
expect_ok   "pw-r2 has static route to plant segment" sh -c "ip -n $NS_R2 route show $NET_PLANT | grep -q $R1_WAN_IP"
expect_ok   "plant -> API ping (2 router hops)"      plant ping -c 1 -W 2 "$API_IP"
expect_ok   "ops -> API ping"                        ops ping -c 1 -W 2 "$API_IP"
echo
echo "Security policy"
expect_ok   "plant -> API HTTPS with CA verification" plant curl -sf --noproxy '*' --cacert "$CA_CERT" -m 5 "$API_URL/health"
expect_fail "plant -> API without trusting the lab CA" plant curl -sf --noproxy '*' -m 5 "$API_URL/health"
expect_fail "plant -> API plain HTTP on 8443"         plant curl -sf --noproxy '*' -m 5 "http://$API_HOST:$API_PORT/health"
expect_fail "plant -> Redis tcp/6379 (bypass the API)" plant nc -z -w 2 "$DB_IP" "$REDIS_PORT"
expect_fail "plant -> Redis ping"                     plant ping -c 1 -W 1 "$DB_IP"
expect_fail "ops -> Redis tcp/6379"                   ops nc -z -w 2 "$DB_IP" "$REDIS_PORT"
expect_fail "plant -> API tcp/22 (port not in policy)" plant nc -z -w 2 "$API_IP" 22
expect_fail "plant -> ops zone"                       plant ping -c 1 -W 1 "$OPS_IP"
expect_ok   "API -> Redis tcp/6379 with password"     api sh -c "REDISCLI_AUTH='$REDIS_PASSWORD' redis-cli -h $DB_IP ping | grep -q PONG"
expect_fail "API -> Redis without password"           api sh -c "redis-cli -h $DB_IP ping | grep -q PONG"
echo
echo "Service"
expect_ok   "write + read back through API and Redis" plant "$PY" "$LAB_ROOT/client/roundtrip.py"
expect_ok   "datastore holds >= 1000 readings"        plant sh -c "curl -sf --noproxy '*' --cacert $CA_CERT $API_URL/stats | grep -Eq '\"readings_total\":\"[0-9]{4,}\"'"
expect_ok   "invalid payload is rejected with 422"    plant sh -c "[ \$(curl -s --noproxy '*' --cacert $CA_CERT -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{\"machine_id\":\"X\"}' $API_URL/telemetry) = 422 ]"
expect_ok   "unknown machine returns 404"             plant sh -c "[ \$(curl -s --noproxy '*' --cacert $CA_CERT -o /dev/null -w '%{http_code}' $API_URL/machines/NOPE) = 404 ]"
summary
} 2>&1 | tee "$OUT"
rc=${PIPESTATUS[0]}
fix_owner
exit "$rc"
