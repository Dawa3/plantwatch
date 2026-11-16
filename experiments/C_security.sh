#!/usr/bin/env bash
# Module C - Network security evidence:
# rulesets, TLS details, permitted traffic, denied traffic, counters and a capture.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab
OUT="$EVID_DIR/C_security"; mkdir -p "$OUT"
PCAP="$OUT/r2_wan_security.pcap"

# Capture on the data-centre router's WAN interface while the tests run.
ip netns exec "$NS_R2" tcpdump -i r2-wan -nn -U -Z root -w "$PCAP" \
  "tcp port $API_PORT or host $DB_IP or icmp" >/dev/null 2>&1 &
CAP=$!
sleep 1.5

{
header "Module C: network security"

section "Ruleset: data-centre router pw-r2 (forward policy drop)"
r2 nft list ruleset
section "Ruleset: edge router pw-r1"
r1 nft list ruleset
section "Ruleset: Redis host firewall pw-db"
db nft list ruleset

section "Counters before the tests (pw-r2)"
r2 nft list counters

section "TLS: what the client negotiates with the API"
run plant sh -c "openssl s_client -connect $API_IP:$API_PORT -servername $API_HOST -CAfile $CA_CERT -brief </dev/null"
echo "Server certificate:"
openssl x509 -in "$CERT_DIR/api.pem" -noout -subject -issuer -dates -ext subjectAltName

section "ALLOWED: plant -> API over TLS, certificate verified against the lab CA"
run plant curl -sS -v --noproxy '*' --cacert "$CA_CERT" "$API_URL/health"

section "DENIED: plant -> Redis directly (bypassing the API)"
run plant nc -vz -w 3 "$DB_IP" "$REDIS_PORT"
run plant ping -c 2 -W 1 "$DB_IP"

section "DENIED: TLS client that does not trust the lab CA"
run plant curl -sS --noproxy '*' -m 5 "$API_URL/health"
section "DENIED: plain HTTP to the TLS port"
run plant curl -sS --noproxy '*' -m 5 "http://$API_HOST:$API_PORT/health"

section "DENIED: Redis without the password, even from the permitted API host"
run api redis-cli -h "$DB_IP" ping

section "Pass/fail summary of the policy"
expect_ok   "plant -> API tcp/8443 HTTPS (verified)"        plant curl -sf --noproxy '*' --cacert "$CA_CERT" -m 5 "$API_URL/health"
expect_ok   "ops   -> API tcp/8443 HTTPS (verified)"        ops   curl -sf --noproxy '*' --cacert "$CA_CERT" -m 5 "$API_URL/health"
expect_ok   "API   -> Redis tcp/6379 with password"         api sh -c "REDISCLI_AUTH='$REDIS_PASSWORD' redis-cli -h $DB_IP ping | grep -q PONG"
expect_fail "plant -> Redis tcp/6379"                       plant nc -z -w 2 "$DB_IP" "$REDIS_PORT"
expect_fail "plant -> Redis ICMP"                           plant ping -c 1 -W 1 "$DB_IP"
expect_fail "ops   -> Redis tcp/6379"                       ops nc -z -w 2 "$DB_IP" "$REDIS_PORT"
expect_fail "plant -> API tcp/22 (not in policy)"           plant nc -z -w 2 "$API_IP" 22
expect_fail "plant -> API tcp/6379 (not in policy)"         plant nc -z -w 2 "$API_IP" "$REDIS_PORT"
expect_fail "plant -> ops zone (blocked at pw-r1)"          plant ping -c 1 -W 1 "$OPS_IP"
expect_fail "API without CA trust (certificate rejected)"   plant curl -sf --noproxy '*' -m 5 "$API_URL/health"
expect_fail "plain HTTP on tcp/8443"                        plant curl -sf --noproxy '*' -m 5 "http://$API_HOST:$API_PORT/health"
expect_fail "Redis without password from API host"          api sh -c "redis-cli -h $DB_IP ping | grep -q PONG"

section "Counters after the tests (pw-r2): allow_* and deny_* both increased"
r2 nft list counters
section "Counters after the tests (pw-r1)"
r1 nft list counters

sleep 1; kill -INT $CAP 2>/dev/null; wait $CAP 2>/dev/null

section "Packet evidence from $PCAP"
echo "--- denied flow: SYN to Redis answered by the router with ICMP admin-prohibited"
tcpdump -r "$PCAP" -nn -tttt "host $DB_IP or icmp[icmptype] == icmp-unreach" 2>/dev/null | head -8
echo
echo "--- allowed flow: TCP handshake + TLS records on tcp/$API_PORT (first packets)"
tcpdump -r "$PCAP" -nn -tttt "tcp port $API_PORT" 2>/dev/null | head -12
summary
} 2>&1 | tee "$OUT/security.txt"
rc=${PIPESTATUS[0]}
kill -INT $CAP 2>/dev/null
fix_owner
echo "Saved: $OUT/security.txt and $PCAP"
exit "$rc"
