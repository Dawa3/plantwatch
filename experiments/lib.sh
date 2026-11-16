#!/usr/bin/env bash
# Helpers shared by the experiment scripts.
. "$(dirname "${BASH_SOURCE[0]}")/../lab/services.sh"

plant() { in_ns "$NS_PLANT" "$@"; }
ops()   { in_ns "$NS_OPS" "$@"; }
api()   { in_ns "$NS_API" "$@"; }
db()    { in_ns "$NS_DB" "$@"; }
r1()    { in_ns "$NS_R1" "$@"; }
r2()    { in_ns "$NS_R2" "$@"; }

# curl that trusts only the lab CA
pcurl() { curl -sS --noproxy '*' --cacert "$CA_CERT" "$@"; }
# redis-cli with the password taken from the environment (never on the command line)
rcli() { env REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --no-auth-warning -h "$DB_IP" "$@"; }

section() { printf '\n==================== %s ====================\n' "$*"; }

# run <command...>   print the command, then its output
run() { echo "\$ $*"; "$@" 2>&1; local rc=$?; echo "[exit $rc]"; echo; return $rc; }

PASS=0; FAIL=0
# expect_ok   "<description>" <command...>   the command must succeed
# expect_fail "<description>" <command...>   the command must fail (a denied path)
expect_ok() {
  local d="$1"; shift
  if "$@" >/dev/null 2>&1; then PASS=$((PASS+1)); printf '  PASS  %-9s %s\n' "(works)" "$d"
  else FAIL=$((FAIL+1)); printf '  FAIL  %-9s %s\n' "(works)" "$d"; fi
}
expect_fail() {
  local d="$1"; shift
  if "$@" >/dev/null 2>&1; then FAIL=$((FAIL+1)); printf '  FAIL  %-9s %s\n' "(blocked)" "$d"
  else PASS=$((PASS+1)); printf '  PASS  %-9s %s\n' "(blocked)" "$d"; fi
}
summary() { echo; echo "Result: $PASS passed, $FAIL failed"; [ "$FAIL" -eq 0 ]; }

header() {
  echo "PlantWatch - $1"
  echo "Generated: $(now_iso)   Host kernel: $(uname -r)"
}
