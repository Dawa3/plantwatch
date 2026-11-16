#!/usr/bin/env bash
# Shared settings for every PlantWatch script. Source it, do not run it.

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$LAB_ROOT/run"
LOG_DIR="$RUN_DIR/logs"
CERT_DIR="$RUN_DIR/certs"
EVID_DIR="$LAB_ROOT/evidence"
VENV="$LAB_ROOT/.venv"
if [ -x "$VENV/bin/python" ]; then PY="$VENV/bin/python"; else PY="$(command -v python3)"; fi

# ---- zones (network namespaces) -------------------------------------------
NS_PLANT=pw-plant   # client zone: simulated machines on the plant floor
NS_OPS=pw-ops       # operations zone: monitoring, health probes, alert consumer
NS_R1=pw-r1         # edge router (plant side)
NS_R2=pw-r2         # data-centre router + firewall
NS_API=pw-api       # service zone: HTTPS API
NS_DB=pw-db         # data zone: Redis
ALL_NS="$NS_PLANT $NS_OPS $NS_R1 $NS_R2 $NS_API $NS_DB"

# ---- addressing ------------------------------------------------------------
NET_PLANT=10.14.1.0/24 ; PLANT_IP=10.14.1.10 ; R1_PLANT_IP=10.14.1.1
NET_APP=10.14.2.0/24   ; API_IP=10.14.2.10   ; R2_APP_IP=10.14.2.1
NET_DATA=10.14.3.0/24  ; DB_IP=10.14.3.10    ; R2_DATA_IP=10.14.3.1
NET_OPS=10.14.4.0/24   ; OPS_IP=10.14.4.10   ; R1_OPS_IP=10.14.4.1
NET_WAN=10.14.0.0/30   ; R1_WAN_IP=10.14.0.1 ; R2_WAN_IP=10.14.0.2

API_HOST=api.plantwatch.lab
API_PORT=8443
API_URL="https://$API_HOST:$API_PORT"
REDIS_PORT=6379
IPERF_PORT=5201
CA_CERT="$CERT_DIR/ca.pem"

# Secrets live in .env (git-ignored), created by lab/setup_host.sh
# shellcheck disable=SC1091
[ -f "$LAB_ROOT/.env" ] && . "$LAB_ROOT/.env"

# Lab addresses must never be sent to an HTTP proxy configured on the host.
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}$API_HOST,$API_IP"
export no_proxy="$NO_PROXY"

RUN_USER="${SUDO_USER:-$(id -un)}"

need_root() {
  if [ "$(id -u)" -ne 0 ]; then exec sudo -E bash "$0" "$@"; fi
}

in_ns() { ip netns exec "$@"; }

now_epoch() { date +%s.%3N; }
now_iso()   { date +%Y-%m-%dT%H:%M:%S.%3N%z; }

# Timestamped event log used to correlate network events with application effects.
log_event() {
  mkdir -p "$EVID_DIR"
  printf '%s\t%s\t%s\n' "$(now_epoch)" "$(now_iso)" "$*" >> "$EVID_DIR/events.log"
  echo "[event] $*"
}

fix_owner() {
  chown -R "$RUN_USER": "$EVID_DIR" "$RUN_DIR" 2>/dev/null || true
}

lab_is_up() { [ -e "/var/run/netns/$NS_R2" ]; }

require_lab() {
  lab_is_up || { echo "Lab is not running. Start it with: sudo make up"; exit 1; }
}
