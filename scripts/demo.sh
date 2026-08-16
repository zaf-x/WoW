#!/usr/bin/env bash
# One-command WoW VPN demo: generate a self-signed certificate and a random
# token, then run the server and a client on the same machine.
#
# Requirements: Linux, root (TUN device + iptables), /dev/net/tun, openssl,
# and the wow-* packages installed from PyPI:
#   pip install wow-common wow-client wow-server
#
# Usage:  sudo bash scripts/demo.sh
# The client panel runs in the foreground; press Ctrl+C to quit, and the
# server is stopped automatically.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "E: run as root (TUN device + iptables required)" >&2
    exit 1
fi

PORT="${WOW_DEMO_PORT:-9999}"
# Egress interface for NAT: the physical interface on the main default
# route. Read from the main table so an active VPN on this host (with its
# own policy routes) does not confuse the probe.
IFACE="$(ip route show table main default 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i=="dev") {print $(i+1); exit}}')"
case "$IFACE" in
    wowtun|wowgateway|tun*) IFACE="eth0" ;;
esac

WORKDIR="$(mktemp -d)"
CERT="$WORKDIR/cert.pem"
KEY="$WORKDIR/key.pem"
TOKEN="$(openssl rand -hex 16)"

cleanup() {
    if [ -n "${SERVER_PID:-}" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

# Self-signed certificate whose SAN covers localhost/127.0.0.1 so the
# client's TLS hostname verification passes when connecting to 127.0.0.1.
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" -days 1 \
    -subj "/CN=wow-demo" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1

echo "== WoW demo: 127.0.0.1:$PORT, egress iface $IFACE =="
echo "token: $TOKEN"

wow-server --host 0.0.0.0 --port "$PORT" --token "$TOKEN" --iface "$IFACE" \
           --cert "$CERT" --key "$KEY" &
SERVER_PID=$!
sleep 1

echo "== connecting client to 127.0.0.1:$PORT =="
wow-client start -s 127.0.0.1 -p "$PORT" -t "$TOKEN" -c "$CERT"
