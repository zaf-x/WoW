# WoW — Wire over Wire

[English](README.md) | [中文](README.zh-CN.md)

[![wow-common](https://img.shields.io/pypi/v/wow-common.svg?label=wow-common)](https://pypi.org/project/wow-common)
[![wow-client](https://img.shields.io/pypi/v/wow-client.svg?label=wow-client)](https://pypi.org/project/wow-client)
[![wow-server](https://img.shields.io/pypi/v/wow-server.svg?label=wow-server)](https://pypi.org/project/wow-server)

A lightweight L2 VPN for Linux: IP packets travel between a client-side
and a server-side TUN device over a TLS-encrypted TCP tunnel.

```
Client App -> TUN ---- TCP + TLS ----> Server -> TUN -> Physical interface
```

## Features

- **L2 (IP) tunneling** over TCP with TLS encryption
- **Dual-stack**: IPv4 (`10.8.0.0/24`) and IPv6 (`fd08::/64`) tunnel networks
- **128-bit token authentication**, with pluggable custom auth handlers
- **Masquerade mode**: silently drops bad auth attempts to camouflage the service
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

## Quick start

### Server

Requires Linux, root, `/dev/net/tun` and a TLS certificate. Install from
PyPI, or from source for development:

```console
# from PyPI
pip install wow-common wow-server
```

```console
# from source
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-server
```

Run the server:

```console
wow-server --host 0.0.0.0 --port 9999 \
           --token <32-hex-chars> --iface eth0 \
           --cert cert.pem --key key.pem
```

Every option can also be set through a `WOW_*` environment variable
(`WOW_HOST`, `WOW_PORT`, `WOW_TOKEN`, `WOW_IFACE`, `WOW_CERT`, `WOW_KEY`).

- `--masquerade`: silently drop bad auth attempts instead of replying
- `--script-auth --auth-script auth.py`: plug in a Python file exporting
  `auth_handler(token: int) -> bool` for custom authentication

### Client

Requires Linux and root (TUN device + raw ICMP socket for the latency
probe).

```console
# from PyPI
pip install wow-common wow-client
```

```console
# from source
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-client
```

```console
# connect directly (trust a custom CA with -c ca.pem)
wow-client start -s vpn.example.com -p 9999 -t <32-hex-chars>

# save servers as named profiles, then pick one interactively
wow-client save myserver -s vpn.example.com -p 9999 -t <32-hex-chars>
wow-client launch
```

## Security notes

- Authentication uses a shared 128-bit token (32 hex chars) exchanged
  inside the TLS session; brute-forcing it is infeasible.
- Run the server with `--masquerade` to make it behave like a dead port
  to unauthenticated scanners.
- Token-based auth is all-or-nothing: use `--script-auth` when you need
  per-client policies, rate limiting or logging. See
  [docs/authentication.md](docs/authentication.md) for the pluggable
  authentication API.

## License

MIT — see [LICENSE.txt](LICENSE.txt) and each package's `LICENSE.txt`.
