#!/usr/bin/env bash
# One-time host preparation (Ubuntu / WSL2 Ubuntu).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
need_root "$@"

# Run a command as the invoking (non-root) user so files in the repo stay owned by them.
as_user() { if [ "$RUN_USER" = root ]; then "$@"; else sudo -u "$RUN_USER" "$@"; fi; }

echo "==> Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq iproute2 nftables tcpdump iperf3 traceroute iputils-ping \
  netcat-openbsd ethtool curl openssl redis-server redis-tools make unzip kmod \
  python3 python3-venv python3-pip >/dev/null

# The packaged Redis service is not used (Redis runs inside the data namespace).
if command -v systemctl >/dev/null && systemctl is-system-running >/dev/null 2>&1; then
  systemctl disable --now redis-server >/dev/null 2>&1 || true
else
  service redis-server stop >/dev/null 2>&1 || true
fi

echo "==> Python environment"
if [ ! -x "$VENV/bin/python" ]; then
  as_user python3 -m venv "$VENV"
fi
as_user "$VENV/bin/pip" install -q --upgrade pip
as_user "$VENV/bin/pip" install -q -r "$LAB_ROOT/requirements.txt"

echo "==> Secrets (.env, git-ignored)"
if [ ! -f "$LAB_ROOT/.env" ]; then
  echo "REDIS_PASSWORD=$(openssl rand -hex 24)" > "$LAB_ROOT/.env"
  chmod 600 "$LAB_ROOT/.env"
  chown "$RUN_USER": "$LAB_ROOT/.env"
fi

echo "==> TLS certificates"
bash "$LAB_ROOT/lab/gen_certs.sh"

echo "==> Dataset"
as_user bash "$LAB_ROOT/data/get_dataset.sh" || true

mkdir -p "$EVID_DIR" "$RUN_DIR"
fix_owner

echo "==> Kernel preflight"
bash "$LAB_ROOT/lab/preflight.sh" || true
echo
echo "Setup complete. Next: sudo make up"
