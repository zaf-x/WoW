# WoW — Wire over Wire

[English](README.md) | [中文](README.zh-CN.md)

[![GitHub Repo stars](https://img.shields.io/github/stars/zaf-x/WoW?style=social)](https://github.com/zaf-x/WoW)

[![wow-common](https://img.shields.io/pypi/v/wow-common.svg?label=wow-common)](https://pypi.org/project/wow-common)
[![wow-client](https://img.shields.io/pypi/v/wow-client.svg?label=wow-client)](https://pypi.org/project/wow-client)
[![wow-server](https://img.shields.io/pypi/v/wow-server.svg?label=wow-server)](https://pypi.org/project/wow-server)
[![CI](https://github.com/zaf-x/WoW/actions/workflows/ci.yml/badge.svg)](https://github.com/zaf-x/WoW/actions/workflows/ci.yml)

一个轻量级 Linux L3 VPN：IP 数据包通过 TLS 加密的 TCP 隧道，在客户端与
服务端的 TUN 设备之间传输。

```
客户端应用 -> TUN ---- TCP + TLS ----> 服务端 -> TUN -> 物理网卡
```

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

## 仓库结构

| 包 | 作用 |
| --- | --- |
| `wow-client` | VPN 客户端：连接服务端、创建本地 TUN 设备并把流量导入隧道 |
| `wow-server` | VPN 服务端：认证客户端、分配隧道地址并为其流量做 NAT |
| `wow-common` | 共享代码：线上协议封装与 TUN 设备封装 |

线上协议规范见 [docs/protocol.md](docs/protocol.md)。

## 一键体验

克隆仓库并运行演示脚本——它会自动生成自签证书和随机 token，然后在同一台
机器上启动服务端和客户端：

```bash
git clone https://github.com/zaf-x/WoW.git && cd WoW
pip install wow-common wow-client wow-server
sudo bash scripts/demo.sh
```

客户端实时状态面板在前台运行；按 Ctrl+C 退出（服务端会自动停止）。
需要 Linux 和 root（TUN 设备 + iptables）。

## 快速开始

### 服务端

需要 Linux、root、`/dev/net/tun` 和 TLS 证书。可以从 PyPI 安装，或
从源码安装用于开发：

```bash
# 从 PyPI 安装
pip install wow-common wow-server
```

```bash
# 从源码安装
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-server
```

启动服务端：

```bash
wow-server --host-ipv4 0.0.0.0 --host-ipv6 :: --port 9999 \
           --token-file /etc/wow/tokens.secret --iface eth0 \
           --cert cert.pem --key key.pem
```

选项也可以通过 `WOW_*` 环境变量或可选的 TOML 配置文件设置（`--config`，
默认 `/etc/wow/config.toml`，模板见
[`templates/config.toml`](templates/config.toml)）。优先级为
命令行参数 > TOML > 环境变量 > 默认值。环境变量有
（`WOW_HOST_IPV4`、`WOW_HOST_IPV6`、`WOW_PORT`、`WOW_TOKEN_FILE`、
`WOW_IFACE`、`WOW_CERT`、`WOW_KEY`、`WOW_IPV6_PREFIX`、
`WOW_IPV6_PROXY_NDP`、`WOW_AUTH_SCRIPT`、
`WOW_MASQUERADE`、`WOW_IDLE_SCRIPT`、`WOW_IDLE_TIMER`、
`WOW_IPV6_ROTATE_INTERVAL`、`WOW_API_HOST`、`WOW_API_PORT`、
`WOW_API_TOKEN`、`WOW_VERBOSE`）。

- `--masquerade`：对错误认证回复假成功，随后静默丢弃其流量
- `--auth-script auth.py`：使用导出
  `auth_handler(token: int) -> tuple[bool, int]` 的 Python 文件做
  自定义认证（返回判定结果与稳定的 remote id）
- `--idle-script idle.py --idle-timer 600`：当服务端在指定秒数内没有
  任何客户端时，运行 Python 文件里的 `idle_callback()`——例如闲置实例
  自动关机
- `--ipv6-rotate-interval 3600`：每隔指定秒数为每个客户端从隧道前缀
  重新分配一个随机 IPv6 地址（隐私轮换；默认 1 小时，0 关闭；仅全局
  前缀生效——ULA/NAT66 不轮换）。地址更换会断开现有连接，相当于换
  了一次公网 IP。
- `--api-host 127.0.0.1 --api-port 8000 --api-token <secret>`：在同一
  事件循环上提供管理 API（FastAPI）：`GET /health`、`GET /clients`、
  `POST /clients/{id}/kick`、`GET /stats`。端口为 0 时关闭；建议只绑
  回环地址和/或设置 bearer token——该 API 能踢掉在线客户端。
  `--api-cors`（默认 `*`）列出允许调用 API 的浏览器来源——独立的
  [wow-mgmt-dashboard](https://github.com/zaf-x/wow-mgmt-dashboard)
  面板就是用它。

完整的生产环境部署（systemd、TLS、安全加固）见
[docs/deployment.zh-CN.md](docs/deployment.zh-CN.md)。

### 客户端

需要 Linux 和 root（TUN 设备 + 延迟探测用的原始 ICMP socket）。

```bash
# 从 PyPI 安装
pip install wow-common wow-client
```

```bash
# 从源码安装
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-client
```

```bash
# 直接连接（用 -c ca.pem 信任自定义 CA）
sudo wow-client start -s vpn.example.com -p 9999 -t <32位hex>

# 把服务器存成命名配置，再交互式选择
sudo wow-client save myserver -s vpn.example.com -p 9999 -t <32位hex>
sudo wow-client launch
```

> 若 `sudo` 提示 `wow-client: command not found`，说明可执行文件不在
> sudo 的 PATH 里（例如 pipx 或 `--user` 装到了 `~/.local/bin`）——
> 改用 `sudo "$(which wow-client)" ...`。

## 安全说明

- 每个用户使用 128-bit token（32 位 hex），在 TLS 会话内传输，
  暴力破解不可行。
- 用 `--masquerade` 启动服务端，可以让未认证的扫描器看到一个
  "开着但无用"的端口。
- 需要按客户端做策略、限流或日志时，使用 `--auth-script`。可插拔
  认证 API 见 [docs/authentication.zh-CN.md](docs/authentication.zh-CN.md)。

## License

MIT — 见 [LICENSE.txt](LICENSE.txt) 及各包内的 `LICENSE.txt`。
