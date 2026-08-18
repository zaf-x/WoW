# WoW — Wire over Wire

[English](README.md) | [中文](README.zh-CN.md)

[![GitHub Repo stars](https://img.shields.io/github/stars/zaf-x/WoW?style=social)](https://github.com/zaf-x/WoW)

[![wow-common](https://img.shields.io/pypi/v/wow-common.svg?label=wow-common)](https://pypi.org/project/wow-common)
[![wow-client](https://img.shields.io/pypi/v/wow-client.svg?label=wow-client)](https://pypi.org/project/wow-client)
[![wow-server](https://img.shields.io/pypi/v/wow-server.svg?label=wow-server)](https://pypi.org/project/wow-server)
[![CI](https://github.com/zaf-x/WoW/actions/workflows/ci.yml/badge.svg)](https://github.com/zaf-x/WoW/actions/workflows/ci.yml)

A lightweight L3 VPN for Linux: IP packets travel between a client-side
and a server-side TUN device over a TLS-encrypted TCP tunnel.

```
Client App -> TUN ---- TCP + TLS ----> Server -> TUN -> Physical interface
```

## Features

- **L3 (IP) tunneling** over TCP with TLS encryption
- **Dual-stack**: IPv4 (`10.8.0.0/24`) and IPv6 tunnel networks — ULA
  `fd08::/64` by default, or a public prefix for global IPv6 addresses
- **128-bit token authentication**, with pluggable custom auth handlers
- **Masquerade mode**: answers bad auth attempts with a fake success, then silently drops their traffic
- **NAT** for client traffic via `iptables` / `ip6tables`
- **Policy routing** with a `fwmark` bypass so the VPN's own traffic does not loop back into the tunnel
- **DNS binding** through the tunnel (`resolvectl`)
- **Live status panel**: transfer rates, client↔server and client↔internet latency

## Repository layout

| Package | Purpose |
| --- | --- |
| `wow-client` | VPN client: connects to the server, sets up the local TUN device and routes traffic through the tunnel |
| `wow-server` | VPN server: authenticates clients, assigns tunnel addresses and NATs their traffic |
| `wow-common` | Shared code: wire protocol framing and the TUN device wrapper |

See [docs/protocol.md](docs/protocol.md) for the wire protocol specification.

## Try it in one command

Clone the repo and run the demo script — it generates a self-signed
certificate and a random token, then starts the server and a client on
the same machine:

```bash
git clone https://github.com/zaf-x/WoW.git && cd WoW
pip install wow-common wow-client wow-server
sudo bash scripts/demo.sh
```

The client's live status panel runs in the foreground; press Ctrl+C to
quit (the server is stopped automatically). Requires Linux and root
(TUN device + iptables).

## Quick start

### Server

Requires Linux, root, `/dev/net/tun` and a TLS certificate. Install from
PyPI, or from source for development:

```bash
# from PyPI
pip install wow-common wow-server
```

```bash
# from source
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-server
```

Run the server:

```bash
wow-server --host-ipv4 0.0.0.0 --host-ipv6 :: --port 9999 \
           --token <32-hex-chars> --iface eth0 \
           --cert cert.pem --key key.pem
```

Options can also come from a `WOW_*` environment variable or an optional
TOML config file (`--config`, default `/etc/wow/config.toml`; template:
[`templates/config.toml`](templates/config.toml)). Precedence is
command-line flag > TOML > env > default. The env variables are
(`WOW_HOST_IPV4`, `WOW_HOST_IPV6`, `WOW_PORT`, `WOW_TOKEN`, `WOW_IFACE`,
`WOW_CERT`, `WOW_KEY`, `WOW_IPV6_PREFIX`, `WOW_IPV6_PROXY_NDP`,
`WOW_SCRIPT_AUTH`, `WOW_AUTH_SCRIPT`, `WOW_MASQUERADE`,
`WOW_IDLE_SCRIPT`, `WOW_IDLE_TIMER`, `WOW_IPV6_ROTATE_INTERVAL`,
`WOW_API_HOST`, `WOW_API_PORT`, `WOW_API_TOKEN`, `WOW_VERBOSE`).

- `--masquerade`: reply to bad auth attempts with a fake success, then
  silently drop their traffic
- `--script-auth --auth-script auth.py`: plug in a Python file exporting
  `auth_handler(token: int) -> tuple[bool, int]` for custom
  authentication (verdict, per-connection id)
- `--idle-script idle.py --idle-timer 600`: run `idle_callback()` from a
  Python file once the server has had no clients for the given number of
  seconds — e.g. auto-shutdown of an unused instance
- `--ipv6-rotate-interval 3600`: reassign every client a new random IPv6
  address from the tunnel prefix on this interval (privacy rotation;
  default 1 hour, 0 disables). The address swap drops existing
  connections, like renewing a public IP.
- `--api-host 127.0.0.1 --api-port 8000 --api-token <secret>`: management
  API (FastAPI) served on the same event loop: `GET /health`,
  `GET /clients`, `POST /clients/{id}/kick`, `GET /stats`. Port 0
  disables it; keep it on loopback and/or set a bearer token, since it
  can kick connected clients.

For a full production setup (systemd, TLS, hardening), see
[docs/deployment.md](docs/deployment.md).

### Client

Requires Linux and root (TUN device + raw ICMP socket for the latency
probe).

```bash
# from PyPI
pip install wow-common wow-client
```

```bash
# from source
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-client
```

```bash
# connect directly (trust a custom CA with -c ca.pem)
sudo wow-client start -s vpn.example.com -p 9999 -t <32-hex-chars>

# save servers as named profiles, then pick one interactively
sudo wow-client save myserver -s vpn.example.com -p 9999 -t <32-hex-chars>
sudo wow-client launch
```

> If `sudo` reports `wow-client: command not found`, the binary lives
> outside sudo's PATH (e.g. a pipx or `--user` install in `~/.local/bin`) —
> run `sudo "$(which wow-client)" ...` instead.

## Security notes

- Authentication uses a shared 128-bit token (32 hex chars) exchanged
  inside the TLS session; brute-forcing it is infeasible.
- Run the server with `--masquerade` to make it behave like a live but
  useless endpoint to unauthenticated scanners.
- Token-based auth is all-or-nothing: use `--script-auth` when you need
  per-client policies, rate limiting or logging. See
  [docs/authentication.md](docs/authentication.md) for the pluggable
  authentication API.

## License

MIT — see [LICENSE.txt](LICENSE.txt) and each package's `LICENSE.txt`.
