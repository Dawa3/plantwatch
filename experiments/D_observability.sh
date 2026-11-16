#!/usr/bin/env bash
# Module D - Observability evidence:
# trace ONE transaction through three capture points and the logs, then
# collect log samples, flow summaries and listening ports.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab
OUT="$EVID_DIR/D_observability"; mkdir -p "$OUT"

capture() {  # capture <ns> <dev> <file> <filter>
  ip netns exec "$1" tcpdump -i "$2" -nn -U -Z root -w "$3" "$4" >/dev/null 2>&1 &
}

trace_once() {
  rm -f "$OUT"/*.pcap
  capture "$NS_PLANT" eth0    "$OUT/1_plant_client.pcap" "host $API_IP";        C1=$!
  capture "$NS_R2"    r2-wan  "$OUT/2_r2_wan_tls.pcap"   "tcp port $API_PORT";  C2=$!
  capture "$NS_R2"    r2-data "$OUT/3_r2_data_redis.pcap" "tcp port $REDIS_PORT"; C3=$!
  sleep 1.5
  plant "$PY" "$LAB_ROOT/client/trace_request.py" > "$OUT/trace_client.json"
  sleep 1
  kill -INT $C1 $C2 $C3 2>/dev/null; wait $C1 $C2 $C3 2>/dev/null
}

# A capture that happened to include a new Redis connection would contain the
# AUTH command. Never keep such a file: repeat the trace on the warm connection.
for attempt in 1 2 3 4; do
  trace_once
  if grep -aq "$REDIS_PASSWORD" "$OUT/3_r2_data_redis.pcap"; then
    echo "capture contained the Redis AUTH exchange - discarding and repeating (attempt $attempt)"
    rm -f "$OUT/3_r2_data_redis.pcap"
  else
    break
  fi
done

RID_W="$(sed -n 's/.*"request_id": "\([a-f0-9]*\)".*/\1/p' "$OUT/trace_client.json" | sed -n 1p)"
RID_R="$(sed -n 's/.*"request_id": "\([a-f0-9]*\)".*/\1/p' "$OUT/trace_client.json" | sed -n 2p)"

{
header "Module D: observability - one transaction, three vantage points"

section "1. Client view (plant zone): request ids and timing split"
cat "$OUT/trace_client.json"

section "2. API log lines for the same request ids ($RID_W write, $RID_R read)"
grep -E "\"rid\":\"($RID_W|$RID_R)\"" "$LOG_DIR/api.log"

section "3. Capture on pw-r2 r2-wan (client <-> API, tcp/$API_PORT): handshake then encrypted records"
tcpdump -r "$OUT/2_r2_wan_tls.pcap" -nn -tttt 2>/dev/null | head -24
echo "..."
echo "packets on this flow: $(tcpdump -r "$OUT/2_r2_wan_tls.pcap" -nn 2>/dev/null | wc -l)"

section "4. Capture on pw-r2 r2-data (API <-> Redis, tcp/$REDIS_PORT): commands of the same transaction"
tcpdump -r "$OUT/3_r2_data_redis.pcap" -nn -tttt 2>/dev/null | head -12
echo
echo "Redis commands visible in the payload (RESP protocol, reassembled as text):"
tcpdump -r "$OUT/3_r2_data_redis.pcap" -nn -A 2>/dev/null | tr -d '\r' \
  | grep -aoE '^(HGET|MULTI|XADD|SADD|HSET|HINCRBY|EXEC|HGETALL|PING|telemetry:[A-Z0-9]+|machine:[A-Z0-9]+|tool_wear_limit)$' \
  | paste -sd' ' | fold -s -w 110

section "5. Is the payload readable on the wire?"
printf 'machine id "TRACE01" found in client-side capture (TLS)  : %s occurrences\n' "$(grep -ac TRACE01 "$OUT/2_r2_wan_tls.pcap")"
printf 'machine id "TRACE01" found in data-segment capture (RESP): %s occurrences\n' "$(grep -ac TRACE01 "$OUT/3_r2_data_redis.pcap")"
echo "=> TLS hides the application data between client and API. Inside the data"
echo "   centre the Redis protocol is plaintext; that segment is protected by the"
echo "   firewall rules (Module C), not by encryption."

section "6. Flows seen at each capture point (src > dst, packet count)"
for f in "$OUT"/*.pcap; do
  echo "--- $(basename "$f")"
  tcpdump -r "$f" -nn -q 2>/dev/null | awk '{print $3, $4, $5}' | sed 's/:$//' | sort | uniq -c | sort -rn | head -6
done

section "7. Listening sockets per zone"
for ns in $NS_API $NS_DB $NS_PLANT $NS_OPS; do echo "--- $ns"; in_ns "$ns" ss -H -tlnp | awk '{print $1, $4, $6}'; done

section "8. Log samples"
echo "--- API request log (last 8 lines, JSON, one line per request)"
tail -n 8 "$LOG_DIR/api.log"
echo
echo "--- API warnings and errors (last 8)"
grep -E '"level":"(WARN|ERROR)"' "$LOG_DIR/api.log" | tail -n 8
echo
echo "--- Redis server log (last 8 lines)"
tail -n 8 "$LOG_DIR/redis.log"
echo
echo "--- Lab event log (last 10 events)"
tail -n 10 "$EVID_DIR/events.log" 2>/dev/null

section "9. Firewall counters on pw-r2 (traffic accounting)"
r2 nft list counters
} 2>&1 | tee "$OUT/observability.txt"
fix_owner
echo "Saved: $OUT/observability.txt and three .pcap files (open them in Wireshark)"
