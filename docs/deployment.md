# Deployment Guide

[English](deployment.md) | [中文](deployment.zh-CN.md)

This guide walks through running a WoW VPN server on a Linux VPS with
systemd and a Let's Encrypt certificate, then connecting a client.

## Prerequisites

- A Linux VPS (Ubuntu/Debian) with root access and `/dev/net/tun`:
  `ls -l /dev/net/tun`
- A domain name pointing to the server (only needed for a Let's Encrypt
  certificate; a self-signed CA works too)
- Python 3.10+

## 1. Install

```console
pip install wow-common wow-server
```

Or from source:

```console
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-server
```

## 2. TLS certificate

With certbot (requires a domain):

```console
apt install certbot
certbot certonly --standalone -d vpn.example.com
```

The server needs the fullchain and private key:

```console
ln -s /etc/letsencrypt/live/vpn.example.com/fullchain.pem /opt/wow/cert.pem
ln -s /etc/letsencrypt/live/vpn.example.com/privkey.pem  /opt/wow/key.pem
```

Without a domain, generate a self-signed CA and sign a server
certificate with it; clients then trust the CA via `-c ca.pem`.

## 3. Authentication token

```console
openssl rand -hex 16
```

The client must present this 128-bit token to connect. See
[authentication.md](authentication.md) for pluggable auth alternatives.

## 4. Open the port

Allow the tunnel port through the firewall and the provider's security
group (e.g. `ufw allow 443/tcp`). Port 443 is a good choice: the tunnel
is already TLS, so the listener is indistinguishable from HTTPS.

## 5. systemd service

`/opt/wow/wow-server.conf` (keep it owner-only, it holds the token):

```ini
WOW_HOST=0.0.0.0
WOW_PORT=443
WOW_TOKEN=<32-hex-chars>
WOW_IFACE=eth0
WOW_CERT=/opt/wow/cert.pem
WOW_KEY=/opt/wow/key.pem
```

`/etc/systemd/system/wow-server.service`:

```ini
[Unit]
Description=WoW VPN server
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/wow/venv/bin/wow-server
EnvironmentFile=/opt/wow/wow-server.conf
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```console
chmod 600 /opt/wow/wow-server.conf
systemctl daemon-reload
systemctl enable --now wow-server
```

> `WOW_IFACE` must be the physical egress interface (find it with
> `ip route get 1.1.1.1`). The server creates a per-client TUN device,
> enables IPv4/IPv6 forwarding and sets up iptables/ip6tables
> MASQUERADE on that interface. If IPv6 NAT is unavailable the tunnel
> still carries IPv6 between peers, just not to the internet.

## 6. Verify the server

```console
systemctl status wow-server
ss -tlnp | grep 443
journalctl -u wow-server -f
```

You should see `Server listening on 0.0.0.0:443`.

## 7. Connect a client

On a Linux machine with root (TUN device + raw ICMP socket):

```console
pip install wow-common wow-client

# save a named profile, then launch it interactively
wow-client save myvpn -s vpn.example.com -p 443 -t <32-hex-chars>
wow-client launch
```

Or connect directly:

```console
wow-client start -s vpn.example.com -p 443 -t <32-hex-chars>
```

## 8. Test the tunnel

The status panel shows the assigned addresses (`10.8.0.x/24` and
`fd08::x/64`). With the tunnel up:

```console
ping 10.8.0.1                # server over IPv4
ping -6 fd08::1              # server over IPv6
curl -4 https://api.ipify.org   # public IPv4 via the tunnel
curl -6 https://api6.ipify.org  # public IPv6 via the tunnel
```

## 9. Public IPv6 (optional)

By default clients get ULA IPv6 (`fd08::/64`) and are NATed like IPv4.
To hand out **global IPv6 addresses** instead, point the tunnel network
at a public prefix the provider routes to your server:

```ini
WOW_IPV6_PREFIX=2001:db8:1:2::/64
```

(or pass `--ipv6-prefix` on the command line). NAT66 is then disabled
automatically, so clients reach the internet with their own global
address — true end-to-end IPv6, no NAT.

> `2001:db8::/32` is the RFC 3849 documentation range, shown as a
> placeholder — use your provider's real global prefix. NAT66 stays on
> for non-global prefixes (ULA, documentation), so the auto-off only
> kicks in with a genuinely routable range.

Provider setups differ:

- **Routed prefix** (most VPS "additional IPv6" ranges): nothing else to
  do — the server forwards the prefix out of the physical interface.
- **On-link prefix** (e.g. AWS EC2): the kernel must answer NDP for the
  client addresses. Enable proxy NDP on the egress interface and pin
  each client address:

  ```console
  sysctl -w net.ipv6.conf.eth0.proxy_ndp=1
  ip -6 neigh add proxy <client-addr> dev eth0
  ```

Then verify by pinging a client's address from another host.

## 10. Hardening

- Run with `--masquerade` (add it to the unit's `ExecStart` line, e.g.
  `ExecStart=/opt/wow/venv/bin/wow-server --masquerade`) so failed auth
  attempts get a silent dead-end instead of an explicit rejection.
- Use `--script-auth --auth-script auth.py` for per-client policy,
  rate limiting or logging.
- The firewall should only expose the tunnel port; nothing else needs
  to be public.
