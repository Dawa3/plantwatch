#!/usr/bin/env bash
# Create a private lab CA and a server certificate for the API.
# Keys are written to run/certs/ which is git-ignored.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"

mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

if [ -f ca.pem ] && [ -f api.pem ] && [ "${1:-}" != "--force" ]; then
  echo "Certificates already exist in $CERT_DIR (use --force to regenerate)."
  exit 0
fi

# 1. Certificate authority
openssl genrsa -out ca.key 2048 2>/dev/null
openssl req -x509 -new -key ca.key -sha256 -days 365 \
  -subj "/O=PlantWatch Lab/CN=PlantWatch Lab CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" -out ca.pem

# 2. Server key + CSR
openssl genrsa -out api.key 2048 2>/dev/null
openssl req -new -key api.key -subj "/O=PlantWatch Lab/CN=$API_HOST" -out api.csr

# 3. Sign with SAN for both the DNS name and the service address
cat > api.ext <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
extendedKeyUsage=serverAuth
subjectAltName=DNS:$API_HOST,IP:$API_IP
EOF
openssl x509 -req -in api.csr -CA ca.pem -CAkey ca.key -CAcreateserial \
  -days 365 -sha256 -extfile api.ext -out api.pem 2>/dev/null

chmod 600 ca.key api.key
rm -f api.csr api.ext
echo "Created CA and server certificate:"
openssl x509 -in api.pem -noout -subject -issuer -enddate -ext subjectAltName
