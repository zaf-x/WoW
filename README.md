# WoW — Wire over Wire

[English](README.md) | [中文](README.zh-CN.md)

[![GitHub Repo stars](https://img.shields.io/github/stars/zaf-x/WoW?style=social)](https://github.com/zaf-x/WoW)

[![wow-common](https://img.shields.io/pypi/v/wow-common.svg?label=wow-common)](https://pypi.org/project/wow-common)
[![wow-client](https://img.shields.io/pypi/v/wow-client.svg?label=wow-client)](https://pypi.org/project/wow-client)
[![wow-server](https://img.shields.io/pypi/v/wow-server.svg?label=wow-server)](https://pypi.org/project/wow-server)
[![CI](https://github.com/zaf-x/WoW/actions/workflows/ci.yml/badge.svg)](https://github.com/zaf-x/WoW/actions/workflows/ci.yml)

## What is this?

WoW ("Wire over Wire") is a lightweight L3 VPN for Linux: IP packets
travel between a client-side and a server-side TUN device over a
TLS-encrypted TCP tunnel. No kernel modules — everything runs in
userspace on top of the standard TUN interface.

```
Client App -> TUN ---- TCP + TLS ----> Server -> TUN -> Physical interface
```

It follows a classic server-client design: the server terminates the
tunnel and routes client traffic, the client creates a local TUN device
and pulls its traffic through. See [Installation](#installation) to get
started.

## Features

- **L3 (IP) tunneling** over TCP with TLS encryption
- **Dual-stack**: IPv4 (`10.8.0.0/24`) and IPv6 tunnel networks — ULA
  `fd08::/64` by default, or a public prefix for global IPv6 addresses
- **128-bit token authentication**, with pluggable custom auth handlers
- **Masquerade mode**: answers bad auth attempts with a fake success,
  then silently drops their traffic
- **NAT** for client traffic via `iptables` / `ip6tables`
- **Policy routing** with a `fwmark` bypass so the VPN's own traffic does
  not loop back into the tunnel
- **DNS binding** through the tunnel (`resolvectl`)
- **Live status panel**: transfer rates, client↔server and
  client↔internet latency
- **Management API** (FastAPI) for monitoring and kicking clients

## Installation

Requires Linux, Python 3.10+ and root (TUN device + iptables).

```bash
# server
pip install wow-server

# client
pip install wow-client
```

For development, install from source:

```bash
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-server    # server
pip install ./wow-common ./wow-client    # client
```

This puts the `wow-server` and `wow-client` commands on your PATH
(`wow-common` is pulled in automatically as a dependency). Both
packages are published on PyPI — see the badges above.

## Documentation

| Document | Description |
| --- | --- |
| [wow-client/README.md](wow-client/README.md) | Client CLI, options and usage |
| [wow-server/README.md](wow-server/README.md) | Server CLI, options and usage |
| [wow-common/README.md](wow-common/README.md) | Shared library: wire protocol framing, TUN wrapper |
| [docs/protocol.md](docs/protocol.md) | Wire protocol specification ([中文](docs/protocol.zh-CN.md)) |
| [docs/authentication.md](docs/authentication.md) | Pluggable authentication API ([中文](docs/authentication.zh-CN.md)) |
| [docs/deployment.md](docs/deployment.md) | Production deployment: systemd, TLS, hardening ([中文](docs/deployment.zh-CN.md)) |

## License

MIT — see [LICENSE.txt](LICENSE.txt) and each package's `LICENSE.txt`.
