# wow-server

[![PyPI - Version](https://img.shields.io/pypi/v/wow-server.svg)](https://pypi.org/project/wow-server)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-server.svg)](https://pypi.org/project/wow-server)

[English](README.md) | [中文](README.zh-CN.md)

The server for the [WoW VPN](https://github.com/zaf-x/WoW) project
(https://github.com/zaf-x/WoW). Accepts TLS clients, authenticates them
with a token file or a custom auth script, creates a gateway TUN device
(one per server, shared by all clients) and NATs their traffic out
through the physical interface. Each client is assigned IPv4
(`10.8.0.0/24`) and an IPv6 tunnel address — ULA `fd08::/64` by default,
or a public prefix (`--ipv6-prefix` / `WOW_IPV6_PREFIX`) for global IPv6.

Requires Linux, root, `/dev/net/tun` and a TLS certificate.

## Quick start

```bash
wow-server --host-ipv4 0.0.0.0 --host-ipv6 :: --port 9999 \
           --token-file /etc/wow/tokens.secret --iface eth0 \
           --cert cert.pem --key key.pem [--masquerade]
```

## Options

Every option can be set with a CLI flag, a `WOW_*` environment variable
or an optional TOML config file (`--config`, template:
[`templates/config.toml`](../templates/config.toml)). Precedence is
**command-line flag > TOML > env > default**. The TOML file groups
options into `[network]`, `[tls]`, `[auth]`, `[idle]` and `[api]`
tables plus a root `verbose` key.

The parameters below are split into a quick-reference table of simple
options and dedicated sections for the ones that need explanation.

### Simple options

| Flag | Env var | Default | Description |
| --- | --- | --- | --- |
| `--config <path>` | — | `/etc/wow/config.toml` | Path to the TOML config file |
| `--host-ipv4 <addr>` | `WOW_HOST_IPV4` | `0.0.0.0` | IPv4 listen address |
| `--host-ipv6 <addr>` | `WOW_HOST_IPV6` | `::` | IPv6 listen address; empty disables it |
| `--port <n>` | `WOW_PORT` | `9999` | Listen port |
| `--iface <name>` | `WOW_IFACE` | required | Physical interface used for NAT, e.g. `ens5` |
| `--cert <file>` | `WOW_CERT` | required | TLS certificate file |
| `--key <file>` | `WOW_KEY` | required | TLS private key file |
| `-v`, `--verbose` | `WOW_VERBOSE` | `false` | Debug logging |

### Authentication

The server accepts a 128-bit token (32 hex chars) from each client and
decides to accept or reject it. Two mutually exclusive modes are
available; a missing token file or auth script makes the server refuse
to start.

**Token file** (`--token-file <file>` / `WOW_TOKEN_FILE`) — the default
mode. The file holds one user per line:

```
<token-hex> <username> <remote-id-hex>
```

- `token-hex` — the 128-bit token as 32 hex chars (generate with
  `openssl rand -hex 16`).
- `username` — a free-form label shown in logs and the management API.
- `remote-id-hex` — the stable 128-bit id handed to the server. Because
  the IPv4 address is derived from this id, a client reconnecting with
  the same token keeps its tunnel addresses.

Blank lines and `#` comments are ignored. Keep the file readable only
by root (`chmod 600`); delete a line to revoke that user.

**Custom auth script** (`--auth-script <file>` / `WOW_AUTH_SCRIPT`) —
replaces the token file with a Python decision. The script is loaded
once at startup and must export:

```python
def auth_handler(token: int) -> tuple[bool, int]:
    ...
```

The tuple is `(verdict, remote_id)`. Return `(True, id)` to accept the
client under `id`; `(False, _)` rejects it. The remote id is what the
management API addresses connections by, and it drives IPv4 assignment:
returning a **fixed** id per user makes reconnects keep the same IPv4
(a stable identity), while a fresh random id (e.g.
`uuid.uuid4().int`) makes every connection anonymous. Use a script for
per-client policy, revocation, rate limiting or logging — the handler
runs synchronously on the server's event loop, so keep it fast and
precompute lookups at module load. Full API: [docs/authentication.md](../docs/authentication.md).

**Masquerade mode** (`--masquerade` / `WOW_MASQUERADE`) — when
authentication fails, the server still answers with a *fake success* and
then silently drops every packet from that connection. To an
unauthenticated scanner the endpoint looks live but useless: every
attempt appears to succeed and nothing ever works. Masqueraded
connections get a throwaway address, never a cached one.

### IPv6 addressing

**Tunnel prefix** (`--ipv6-prefix <prefix>` / `WOW_IPV6_PREFIX`,
default `fd08::/64`) — the IPv6 network clients are assigned from. With
the default ULA prefix, client addresses are only valid inside the
tunnel and their traffic is NAT66'd out like IPv4. Point it at a public
prefix (e.g. a provider-routed `/64`) instead to hand clients *global*
IPv6 addresses that are routable on the internet and reachable from it.
The server itself always takes `network + 1` (so `fd08::1` by default).

**Proxy NDP** (`--ipv6-proxy-ndp` / `WOW_IPV6_PROXY_NDP`) — answers
neighbor discovery for each client's address on the physical interface,
so reply traffic to client addresses reaches the server. Needed only
when the tunnel prefix is *on-link* to the server but **not routed to
it** — e.g. an AWS EC2 ENI that owns only its own `/128` of the subnet.
If the prefix is already routed to the instance — assigned to the ENI
as an IPv6 prefix (prefix delegation) or pointed at it by a VPC
route-table entry — AWS delivers the traffic directly and proxy NDP is
not needed. Only relevant for global prefixes.

**Privacy rotation** (`--ipv6-rotate-interval <n>` /
`WOW_IPV6_ROTATE_INTERVAL`, default `3600`) — every `n` seconds each
client is reassigned a fresh random address from the prefix, blurring
its public IPv6 identity over time. The address is *replaced*, not
added, so existing connections drop at each rotation (like renewing a
public IP). Only global prefixes rotate — ULA/NAT66 never do, since the
client is already hidden behind NAT. Set to `0` to disable.

### Idle auto-shutdown

`--idle-script <file>` (`WOW_IDLE_SCRIPT`) exports a Python
`idle_callback()`; `--idle-timer <n>` (`WOW_IDLE_TIMER`, default `600`)
is how many seconds the server must have **no clients** before the
callback runs. Typical use: shutting down an unused cloud instance.

```python
# idle.py
import os

def idle_callback():
    os.system("systemctl poweroff")
```

The callback runs on the server's event loop — return quickly, and
spawn a thread for blocking work. After it returns the check re-arms, so
a callback that declines to act (e.g. a repair-mode guard that skips the
shutdown) lets the check run again after the next idle window.

### Management API

`--api-host <addr>` / `--api-port <n>` / `--api-token <secret>` /
`--api-cors <origins>` (env `WOW_API_HOST` / `WOW_API_PORT` /
`WOW_API_TOKEN` / `WOW_API_CORS`) enable a FastAPI app served on the
same event loop as the VPN server:

- `GET /health` — server liveness
- `GET /clients` — connected clients (remote id, addresses, peer)
- `POST /clients/{remote_id}/kick` — disconnect a client
- `GET /stats` — server-wide counters and configuration

When `--api-token` is set, every request must present
`Authorization: Bearer <token>`; with an empty token the API is open, so
bind it to loopback (`127.0.0.1`, the default) in that case. The API can
kick connected clients, so do not expose it carelessly. `--api-cors`
(default `*`) lists the browser origins allowed to call it — the
separate [wow-mgmt-dashboard](https://github.com/zaf-x/wow-mgmt-dashboard)
web dashboard uses this. Set `--api-port 0` to disable the API.

## Deployment

For a full production setup — systemd service, certbot TLS certificates,
firewall and hardening — see
[docs/deployment.md](../docs/deployment.md)
([中文](../docs/deployment.zh-CN.md)).

## Install

```bash
pip install .
```

## License

`wow-server` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
