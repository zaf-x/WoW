# WoW — Wire over Wire

[English](README.md) | [中文](README.zh-CN.md)

[![GitHub Repo stars](https://img.shields.io/github/stars/zaf-x/WoW?style=social)](https://github.com/zaf-x/WoW)

[![wow-common](https://img.shields.io/pypi/v/wow-common.svg?label=wow-common)](https://pypi.org/project/wow-common)
[![wow-client](https://img.shields.io/pypi/v/wow-client.svg?label=wow-client)](https://pypi.org/project/wow-client)
[![wow-server](https://img.shields.io/pypi/v/wow-server.svg?label=wow-server)](https://pypi.org/project/wow-server)
[![CI](https://github.com/zaf-x/WoW/actions/workflows/ci.yml/badge.svg)](https://github.com/zaf-x/WoW/actions/workflows/ci.yml)

## 这个项目是啥

WoW（"Wire over Wire"）是一个轻量级 Linux L3 VPN：IP 数据包通过 TLS
加密的 TCP 隧道，在客户端与服务端的 TUN 设备之间传输。无需内核模块——
一切都在用户态运行，基于标准 TUN 接口。

```
客户端应用 -> TUN ---- TCP + TLS ----> 服务端 -> TUN -> 物理网卡
```

采用经典的客户端-服务端设计：服务端终结隧道并转发客户端流量，客户端创建
本地 TUN 设备把流量导入隧道。开始使用见 [安装](#安装)。

## 特性

- **L3（IP）隧道**，基于 TCP + TLS 加密传输
- **双栈**：IPv4（`10.8.0.0/24`）与 IPv6 隧道网络——默认 ULA
  `fd08::/64`，可配公网前缀让客户端拿到全局 IPv6 地址
- **128-bit token 认证**，支持可插拔的自定义认证处理器
- **伪装模式（masquerade）**：对错误认证回复假成功，再静默丢弃其后续流量
- 通过 `iptables` / `ip6tables` 为客户端流量做 **NAT**
- **策略路由**，用 `fwmark` 旁路让 VPN 自身流量不回流进隧道
- 通过隧道绑定 **DNS**（`resolvectl`）
- **实时状态面板**：上下行速率、客户端↔服务端与客户端↔公网延迟
- **管理 API**（FastAPI），用于监控与踢出客户端

## 安装

需要 Linux、Python 3.10+ 和 root（TUN 设备 + iptables）。

```bash
# 服务端
pip install wow-server

# 客户端
pip install wow-client
```

从源码安装（开发用）：

```bash
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-server    # 服务端
pip install ./wow-common ./wow-client    # 客户端
```

安装后 `wow-server` 和 `wow-client` 命令会进入 PATH（`wow-common`
作为依赖自动安装）。两个包都已发布到 PyPI——见上方徽章。

## 文档目录

| 文档 | 说明 |
| --- | --- |
| [wow-client/README.md](wow-client/README.md) | 客户端 CLI、参数与用法（[中文](wow-client/README.zh-CN.md)） |
| [wow-server/README.md](wow-server/README.md) | 服务端 CLI、参数与用法（[中文](wow-server/README.zh-CN.md)） |
| [wow-common/README.md](wow-common/README.md) | 共享库：线上协议封装、TUN 设备封装（[中文](wow-common/README.zh-CN.md)） |
| [docs/protocol.md](docs/protocol.md) | 线上协议规范（[中文](docs/protocol.zh-CN.md)） |
| [docs/authentication.md](docs/authentication.md) | 可插拔认证 API（[中文](docs/authentication.zh-CN.md)） |
| [docs/deployment.md](docs/deployment.md) | 生产环境部署：systemd、TLS、安全加固（[中文](docs/deployment.zh-CN.md)） |

## License

MIT — 见 [LICENSE.txt](LICENSE.txt) 及各包内的 `LICENSE.txt`。
