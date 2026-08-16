# wow-client

The client for the [WoW VPN](https://github.com/zaf-x/WoW#readme): connects to the server over
TLS, authenticates with a 128-bit token, sets up a local TUN device and
routes traffic through the tunnel. A live status panel shows transfer
rates and client↔server / client↔internet latency.

Requires Linux and root (TUN device + raw ICMP socket for the latency
probe).

## Usage

```console
# connect directly (trust a custom CA with -c ca.pem)
wow-client start -s vpn.example.com -p 9999 -t <32-hex-chars>

# save servers as named profiles, then pick one interactively
wow-client save myserver -s vpn.example.com -p 9999 -t <32-hex-chars>
wow-client launch
```

Profiles are stored in `$XDG_CONFIG_HOME/wow-client/config.json`
(`~/.config/wow-client/config.json` by default), readable only by the
owner.

## Install

```console
pip install .
```

## License

`wow-client` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
