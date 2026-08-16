# wow-common

Shared building blocks for the [WoW VPN](https://github.com/zaf-x/WoW#readme):

- `wow_common.protocol` — length-prefixed wire framing and packet
  (de)serialization (authentication, address assignment, tunnel data,
  keepalives). See [docs/protocol.md](https://github.com/zaf-x/WoW/blob/main/docs/protocol.md).
- `wow_common.tun` — Linux TUN device wrapper with policy routing
  (`fwmark` bypass), DNS binding and NAT helpers for IPv4 and IPv6.

## Install

```console
pip install .
```

## License

`wow-common` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
