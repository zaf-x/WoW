# wow-server

The server for the [WoW VPN](../README.md): accepts TLS clients,
authenticates them with a shared 128-bit token (or a custom auth script),
creates a per-client TUN device and NATs their traffic out through the
physical interface. Each client is assigned IPv4 (`10.8.0.0/24`) and
IPv6 (`fd08::/64`) tunnel addresses.

Requires Linux, root, `/dev/net/tun` and a TLS certificate.

## Usage

```console
wow-server --host 0.0.0.0 --port 9999 \
           --token <32-hex-chars> --iface eth0 \
           --cert cert.pem --key key.pem [--masquerade]
```

Every option can also be set through a `WOW_*` environment variable
(`WOW_HOST`, `WOW_PORT`, `WOW_TOKEN`, `WOW_IFACE`, `WOW_CERT`, `WOW_KEY`,
`WOW_SCRIPT_AUTH`, `WOW_AUTH_SCRIPT`).

- `--masquerade`: silently drop bad auth attempts instead of replying
- `--script-auth --auth-script auth.py`: use a Python file exporting
  `auth_handler(token: int) -> bool` for custom authentication

## Install

```console
pip install .
```

## License

`wow-server` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
