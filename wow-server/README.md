# wow-server

[![PyPI - Version](https://img.shields.io/pypi/v/wow-server.svg)](https://pypi.org/project/wow-server)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-server.svg)](https://pypi.org/project/wow-server)

[English](https://github.com/zaf-x/WoW/blob/main/wow-server/README.md) | [中文](https://github.com/zaf-x/WoW/blob/main/wow-server/README.zh-CN.md)

The server for the [WoW VPN](https://github.com/zaf-x/WoW#readme): accepts TLS clients,
authenticates them with a shared 128-bit token (or a custom auth script),
creates a gateway TUN device (one per server, shared by all clients)
and NATs their traffic out through the
physical interface. Each client is assigned IPv4 (`10.8.0.0/24`) and an
IPv6 tunnel address — ULA `fd08::/64` by default, or a public prefix
(`--ipv6-prefix` / `WOW_IPV6_PREFIX`) for global IPv6.

Requires Linux, root, `/dev/net/tun` and a TLS certificate.

## Usage

```console
wow-server --host 0.0.0.0 --port 9999 \
           --token <32-hex-chars> --iface eth0 \
           --cert cert.pem --key key.pem [--masquerade]
```

Most options can also be set through a `WOW_*` environment variable
(`WOW_HOST`, `WOW_PORT`, `WOW_TOKEN`, `WOW_IFACE`, `WOW_CERT`, `WOW_KEY`,
`WOW_IPV6_PREFIX`, `WOW_IPV6_PROXY_NDP`, `WOW_SCRIPT_AUTH`,
`WOW_AUTH_SCRIPT`); `--masquerade` and `--verbose` are CLI-only.

- `--masquerade`: reply to bad auth attempts with a fake success, then
  silently drop their traffic
- `--script-auth --auth-script auth.py`: use a Python file exporting
  `auth_handler(token: int) -> bool` for custom authentication

## Install

```console
pip install .
```

## License

`wow-server` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
