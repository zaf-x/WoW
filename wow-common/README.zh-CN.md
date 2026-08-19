# wow-common

[![PyPI - Version](https://img.shields.io/pypi/v/wow-common.svg)](https://pypi.org/project/wow-common)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-common.svg)](https://pypi.org/project/wow-common)

[English](README.md) | [中文](README.zh-CN.md)

[WoW VPN](https://github.com/zaf-x/WoW#readme) 的共享基础组件：

- `wow_common.protocol` — 长度前缀的线上帧格式与数据包（反）序列化
  （认证、地址分配、隧道数据、心跳）。协议规范见
  [docs/protocol.md](../docs/protocol.md)。
- `wow_common.tun` — Linux TUN 设备封装，包含策略路由（`fwmark` 旁路）、
  DNS 绑定和 IPv4/IPv6 的 NAT 辅助函数。

## 安装

```bash
pip install .
```

## License

`wow-common` 采用 [MIT](https://spdx.org/licenses/MIT.html) 许可证。
