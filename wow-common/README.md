# wow-common

[![PyPI - Version](https://img.shields.io/pypi/v/wow-common.svg)](https://pypi.org/project/wow-common)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-common.svg)](https://pypi.org/project/wow-common)

[English](https://github.com/zaf-x/WoW/blob/main/wow-common/README.md) | [中文](https://github.com/zaf-x/WoW/blob/main/wow-common/README.zh-CN.md)

Shared building blocks for the [WoW VPN](https://github.com/zaf-x/WoW#readme):

- `wow_common.protocol` — length-prefixed wire framing and packet
  (de)serialization (authentication, address assignment, tunnel data,
  keepalives). See [docs/protocol.md](https://github.com/zaf-x/WoW/blob/main/docs/protocol.md).
- `wow_common.tun` — Linux TUN device wrapper with policy routing
  (`fwmark` bypass), DNS binding and NAT helpers for IPv4 and IPv6.

## Install

```bash
pip install .
```

## License

`wow-common` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
