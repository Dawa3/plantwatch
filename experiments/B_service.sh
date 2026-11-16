#!/usr/bin/env bash
# Module B - Distributed service evidence:
# repeatable API queries (success and error responses) and the Redis data model.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need_root "$@"
require_lab
OUT="$EVID_DIR/B_service"; mkdir -p "$OUT"
J='Content-Type: application/json'
W='\n[HTTP %{http_code}  total %{time_total}s]\n'

# req <METHOD> <path> [json-body]  - print a copy-pasteable command, then run it from the plant zone
req() {
  local m="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    echo "\$ curl --cacert run/certs/ca.pem -X $m -H '$J' $API_URL$path -d '$body'"
    plant curl -sS --noproxy '*' --cacert "$CA_CERT" -w "$W" -X "$m" -H "$J" "$API_URL$path" -d "$body"
  else
    echo "\$ curl --cacert run/certs/ca.pem -X $m $API_URL$path"
    plant curl -sS --noproxy '*' --cacert "$CA_CERT" -w "$W" -X "$m" "$API_URL$path"
  fi
  echo
}
# start from a known state so the script gives the same output on every run
plant curl -s --noproxy '*' --cacert "$CA_CERT" -o /dev/null -X PUT -H "$J" "$API_URL/machines/DEMO01/config" -d '{"tool_wear_limit":200}'

{
header "Module B: distributed service (client zone -> HTTPS API -> Redis)"

section "CREATE - POST /telemetry (normal reading)"
req POST /telemetry '{"machine_id":"DEMO01","type":"M","air_temp_k":298.9,"process_temp_k":309.4,"rpm":1503,"torque_nm":41.2,"tool_wear_min":35,"source":"demo"}'

section "CREATE - POST /telemetry (worn tool: raises a TWF alert)"
req POST /telemetry '{"machine_id":"DEMO01","type":"M","air_temp_k":299.1,"process_temp_k":309.6,"rpm":1490,"torque_nm":42.0,"tool_wear_min":215,"source":"demo"}'

section "READ - GET /machines/DEMO01 (latest state)"
req GET "/machines/DEMO01"

section "READ - GET /machines/DEMO01/readings?count=2 (history, newest first)"
req GET "/machines/DEMO01/readings?count=2"

section "UPDATE - PUT /machines/DEMO01/config (raise the tool-wear threshold)"
req PUT /machines/DEMO01/config '{"tool_wear_limit":240}'

section "Effect of the update: the same worn-tool reading no longer raises an alert"
req POST /telemetry '{"machine_id":"DEMO01","type":"M","air_temp_k":299.1,"process_temp_k":309.6,"rpm":1490,"torque_nm":42.0,"tool_wear_min":215,"source":"demo"}'

section "READ - GET /alerts?count=3 and UPDATE - POST /alerts/{id}/ack"
req GET "/alerts?count=3"
AID="$(plant curl -s --noproxy '*' --cacert "$CA_CERT" "$API_URL/alerts?count=1" | sed -n 's/.*"id":"\([0-9-]*\)".*/\1/p')"
req POST "/alerts/$AID/ack"

section "READ - GET /machines and GET /stats"
req GET "/machines"
req GET "/stats"

section "ERROR - unknown machine (404)"
req GET "/machines/DOES-NOT-EXIST"
section "ERROR - invalid payload: missing fields (422)"
req POST /telemetry '{"machine_id":"DEMO01","rpm":1500}'
section "ERROR - out-of-range value (422)"
req POST /telemetry '{"machine_id":"DEMO01","type":"M","air_temp_k":299,"process_temp_k":309,"rpm":-5,"torque_nm":40,"tool_wear_min":10}'
section "ERROR - wrong method (405)"
req DELETE "/machines/DEMO01"

section "Redis data model (queried from the service zone, the only zone allowed to reach Redis)"
echo "\$ redis-cli INFO keyspace";            api_rc() { api env REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning -h "$DB_IP" "$@"; }
api_rc info keyspace | tr -d '\r'
for cmd in "DBSIZE" "SCARD machines" "TYPE machine:M01" "HGETALL machine:M01" "TYPE telemetry:M01" \
           "XLEN telemetry:M01" "XREVRANGE telemetry:M01 + - COUNT 2" "TYPE alerts" "XLEN alerts" \
           "XREVRANGE alerts + - COUNT 1" "HGETALL stats" "CONFIG GET appendonly"; do
  echo; echo "\$ redis-cli $cmd"
  # shellcheck disable=SC2086
  api_rc $cmd
done
} 2>&1 | tee "$OUT/queries.txt"
fix_owner
echo "Saved: $OUT/queries.txt"
