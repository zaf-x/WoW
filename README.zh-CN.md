# WoW — Wire over Wire

[English](README.md) | [中文](README.zh-CN.md)

一个轻量级 Linux L2 VPN：IP 数据包通过 TLS 加密的 TCP 隧道，在客户端与
服务端的 TUN 设备之间传输。

```
客户端应用 -> TUN ---- TCP + TLS ----> 服务端 -> TUN -> 物理网卡
```

## 特性

- **L2（IP）隧道**，基于 TCP + TLS 加密传输
- **双栈**：IPv4（`10.8.0.0/24`）与 IPv6（`fd08::/64`）隧道网络
- **128-bit token 认证**，支持可插拔的自定义认证处理器
- **伪装模式（masquerade）**：静默丢弃错误认证请求，隐藏服务
- 通过 `iptables` / `ip6tables` 为客户端流量做 **NAT**
- **策略路由**，用 `fwmark` 旁路让 VPN 自身流量不回流进隧道
- 通过隧道绑定 **DNS**（`resolvectl`）
- **实时状态面板**：上下行速率、客户端↔服务端与客户端↔公网延迟

## 仓库结构

| 包 | 作用 |
| --- | --- |
| `wow-client` | VPN 客户端：连接服务端、创建本地 TUN 设备并把流量导入隧道 |
| `wow-server` | VPN 服务端：认证客户端、分配隧道地址并为其流量做 NAT |
| `wow-common` | 共享代码：线上协议封装与 TUN 设备封装 |

线上协议规范见 [docs/protocol.md](docs/protocol.md)。

## 快速开始

### 服务端

需要 Linux、root、`/dev/net/tun` 和 TLS 证书。

```console
git clone <本仓库> && cd <本仓库>
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-server

wow-server --host 0.0.0.0 --port 9999 \
           --token <32位hex> --iface eth0 \
           --cert cert.pem --key key.pem
```

所有选项都可以用 `WOW_*` 环境变量设置（`WOW_HOST`、`WOW_PORT`、
`WOW_TOKEN`、`WOW_IFACE`、`WOW_CERT`、`WOW_KEY`）。

- `--masquerade`：静默丢弃错误认证请求，不再回复
- `--script-auth --auth-script auth.py`：使用导出
  `auth_handler(token: int) -> bool` 的 Python 文件做自定义认证

### 客户端

需要 Linux 和 root（TUN 设备 + 延迟探测用的原始 ICMP socket）。

```console
git clone <本仓库> && cd <本仓库>
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-client

# 直接连接（用 -c ca.pem 信任自定义 CA）
wow-client start -s vpn.example.com -p 9999 -t <32位hex>

# 把服务器存成命名配置，再交互式选择
wow-client save myserver -s vpn.example.com -p 9999 -t <32位hex>
wow-client launch
```

## 安全说明

- 认证使用 128-bit 共享 token（32 位 hex），在 TLS 会话内传输，
  暴力破解不可行。
- 用 `--masquerade` 启动服务端，可以让未认证的扫描器看到的是
  一个"死端口"。
- Token 认证是"全有或全无"的：需要按客户端做策略、限流或日志时，
  请使用 `--script-auth`。

## License

MIT — 见 [LICENSE.txt](LICENSE.txt) 及各包内的 `LICENSE.txt`。
