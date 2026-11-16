#!/usr/bin/env bash
# Bring up the complete PlantWatch lab on one Linux host:
#   6 network namespaces, 5 IP segments, 2 routers, firewall policy,
#   Redis, the HTTPS API and an iperf3 server.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/services.sh"
need_root "$@"

[ -f "$CA_CERT" ] || { echo "No certificates found. Run: make setup"; exit 1; }
[ -n "${REDIS_PASSWORD:-}" ] || { echo "No .env found. Run: make setup"; exit 1; }

if lab_is_up; then
  echo "Lab already running - rebuilding it."
  bash "$LAB_ROOT/lab/down.sh" >/dev/null
fi
mkdir -p "$RUN_DIR" "$LOG_DIR" "$EVID_DIR"

echo "==> Creating namespaces"
for ns in $ALL_NS; do
  ip netns add "$ns"
  ip -n "$ns" link set lo up
  # Per-namespace /etc/hosts so that the API name resolves inside each zone.
  mkdir -p "/etc/netns/$ns"
  printf '127.0.0.1 localhost\n%s %s\n' "$API_IP" "$API_HOST" > "/etc/netns/$ns/hosts"
done

# link <nsA> <ifA> <ipA/len> <nsB> <ifB> <ipB/len>
link() {
  ip link add pwtmpa netns "$1" type veth peer name pwtmpb netns "$4"; ip -n "$1" link set pwtmpa name "$2"; ip -n "$4" link set pwtmpb name "$5"
  ip -n "$1" addr add "$3" dev "$2"; ip -n "$1" link set "$2" up
  ip -n "$4" addr add "$6" dev "$5"; ip -n "$4" link set "$5" up
  # Disable segmentation offload so captures show real on-wire packets and
  # the traffic shaper sees MTU-sized frames.
  in_ns "$1" ethtool -K "$2" tso off gso off gro off >/dev/null 2>&1 || true
  in_ns "$4" ethtool -K "$5" tso off gso off gro off >/dev/null 2>&1 || true
}

echo "==> Wiring segments"
link "$NS_PLANT" eth0 "$PLANT_IP/24"   "$NS_R1" r1-plant "$R1_PLANT_IP/24"   # segment 1: plant / clients
link "$NS_OPS"   eth0 "$OPS_IP/24"     "$NS_R1" r1-ops   "$R1_OPS_IP/24"     # segment 4: operations
link "$NS_R1"    r1-wan "$R1_WAN_IP/30" "$NS_R2" r2-wan  "$R2_WAN_IP/30"     # transit (WAN) link
link "$NS_API"   eth0 "$API_IP/24"     "$NS_R2" r2-app   "$R2_APP_IP/24"     # segment 2: application
link "$NS_DB"    eth0 "$DB_IP/24"      "$NS_R2" r2-data  "$R2_DATA_IP/24"    # segment 3: data

echo "==> Routing"
in_ns "$NS_R1" sysctl -qw net.ipv4.ip_forward=1
in_ns "$NS_R2" sysctl -qw net.ipv4.ip_forward=1
ip -n "$NS_PLANT" route add default via "$R1_PLANT_IP"
ip -n "$NS_OPS"   route add default via "$R1_OPS_IP"
ip -n "$NS_API"   route add default via "$R2_APP_IP"
ip -n "$NS_DB"    route add default via "$R2_DATA_IP"
net_repair   # static routes between the two routers

echo "==> Firewall policy"
in_ns "$NS_R1" nft -f "$LAB_ROOT/lab/firewall-r1.nft"
in_ns "$NS_R2" nft -f "$LAB_ROOT/lab/firewall-r2.nft"
in_ns "$NS_DB" nft -f "$LAB_ROOT/lab/firewall-db.nft"

echo "==> Services"
start_redis
start_api
start_iperf

if wait_healthy 30; then
  echo "==> API healthy at $API_URL (from the ops zone)"
else
  echo "API did not become healthy. Check $LOG_DIR/api.out"; fix_owner; exit 1
fi

# Load the dataset on first start (Redis is empty).
count="$(in_ns "$NS_API" env REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -h "$DB_IP" hget stats imported_rows 2>/dev/null || true)"
if [ -z "$count" ]; then
  echo "==> Importing dataset into Redis"
  in_ns "$NS_API" env REDIS_HOST="$DB_IP" REDIS_PASSWORD="$REDIS_PASSWORD" \
    "$PY" "$LAB_ROOT/data/import_dataset.py"
fi

log_event "LAB_UP"
fix_owner
echo
services_status
echo
echo "Lab is up. Next: sudo make test   (then: sudo make experiments)"
