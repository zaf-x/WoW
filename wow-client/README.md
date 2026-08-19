# wow-client

[![PyPI - Version](https://img.shields.io/pypi/v/wow-client.svg)](https://pypi.org/project/wow-client)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-client.svg)](https://pypi.org/project/wow-client)

[English](https://github.com/zaf-x/WoW/blob/main/wow-client/README.md) | [中文](https://github.com/zaf-x/WoW/blob/main/wow-client/README.zh-CN.md)

The client for the [WoW VPN](https://github.com/zaf-x/WoW) project
(https://github.com/zaf-x/WoW). Connects to the server over TLS,
authenticates with a 128-bit token, sets up a local TUN device and
routes traffic through the tunnel. A live status panel shows transfer
rates and client↔server / client↔internet latency.

Requires Linux and root (TUN device + raw ICMP socket for the latency
probe).

## Usage

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

## Options

| Subcommand | Flag | Description |
| --- | --- | --- |
| `start`, `save` | `-s`, `--host <host>` | VPN server hostname or address (required) |
| | `-p`, `--port <n>` | VPN server port (required) |
| | `-t`, `--token <hex>` | 128-bit authentication token, 32 hex chars (required) |
| | `-c`, `--ca-cert <file>` | PEM CA certificate to trust for verifying the server (default: system CA bundle) |
| `save` | `name` | Profile name to save the server under (positional argument) |
| `launch` | — | Pick a saved profile interactively and connect |

## Profiles

Profiles are stored in `$XDG_CONFIG_HOME/wow-client/config.json`
(`~/.config/wow-client/config.json` by default), readable only by the
owner:

```json
{
  "profiles": {
    "myserver": {
      "host": "vpn.example.com",
      "port": 443,
      "token": "<32-hex-chars>",
      "ca_cert": null
    }
  }
}
```

`ca_cert` may be a path to a PEM CA certificate, or `null` to use the
system default CA bundle. The file can also be edited by hand.

## Install

```bash
pip install .
```

## License

`wow-client` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
