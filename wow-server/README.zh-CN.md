# wow-server

[![PyPI - Version](https://img.shields.io/pypi/v/wow-server.svg)](https://pypi.org/project/wow-server)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-server.svg)](https://pypi.org/project/wow-server)

[English](README.md) | [中文](README.zh-CN.md)

[WoW VPN](https://github.com/zaf-x/WoW) 项目的服务端（https://github.com/zaf-x/WoW）。
接受 TLS 客户端，使用 token 文件（或自定义认证脚本）认证，创建一张网关 TUN
设备（每台服务器一张，所有客户端共用）并对其流量做 NAT。每个客户端分配 IPv4
（`10.8.0.0/24`）与一个 IPv6 隧道地址——默认 ULA `fd08::/64`，也可用
`--ipv6-prefix` / `WOW_IPV6_PREFIX` 配公网前缀，让客户端拿到全局 IPv6。

需要 Linux、root、`/dev/net/tun` 和 TLS 证书。

## 快速开始

```bash
wow-server --host-ipv4 0.0.0.0 --host-ipv6 :: --port 9999 \
           --token-file /etc/wow/tokens.secret --iface eth0 \
           --cert cert.pem --key key.pem [--masquerade]
```

## 参数详解

每个选项都可以通过 CLI 参数、`WOW_*` 环境变量或可选的 TOML 配置文件设置
（`--config`，模板见 [`templates/config.toml`](../templates/config.toml)）。
优先级为 **命令行参数 > TOML > 环境变量 > 默认值**。TOML 文件把选项分组为
`[network]`、`[tls]`、`[auth]`、`[idle]`、`[api]` 各表，外加根级 `verbose` 键。

下面先给简单参数的速查表，再对需要展开的参数单独开节讲解。

### 简单参数

| 参数 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--config <path>` | — | `/etc/wow/config.toml` | TOML 配置文件路径 |
| `--host-ipv4 <addr>` | `WOW_HOST_IPV4` | `0.0.0.0` | IPv4 监听地址 |
| `--host-ipv6 <addr>` | `WOW_HOST_IPV6` | `::` | IPv6 监听地址；留空则关闭 |
| `--port <n>` | `WOW_PORT` | `9999` | 监听端口 |
| `--iface <name>` | `WOW_IFACE` | 必填 | 用于 NAT 的物理网卡，如 `ens5` |
| `--cert <file>` | `WOW_CERT` | 必填 | TLS 证书文件 |
| `--key <file>` | `WOW_KEY` | 必填 | TLS 私钥文件 |
| `-v`, `--verbose` | `WOW_VERBOSE` | `false` | 调试日志 |

### 认证

服务端从每个客户端接收 128-bit token（32 位 hex），决定接受或拒绝。有两种
互斥的模式；两者都没配置时服务端拒绝启动。

**Token 文件**（`--token-file <file>` / `WOW_TOKEN_FILE`）——默认模式。
文件每行一个用户：

```
<token-hex> <username> <remote-id-hex>
```

- `token-hex` — 128-bit token，32 位 hex（用 `openssl rand -hex 16` 生成）。
- `username` — 自由文本标签，显示在日志和管理 API 里。
- `remote-id-hex` — 交给服务端的稳定 128-bit id。IPv4 地址由这个 id 推导，
  因此同一 token 重连的客户端能保住原有隧道地址。

空行和 `#` 注释会被忽略。文件应只允许 root 读取（`chmod 600`）；
删除某一行即吊销该用户。

**自定义认证脚本**（`--auth-script <file>` / `WOW_AUTH_SCRIPT`）——用
Python 脚本取代 token 文件做判定。脚本在启动时加载一次，必须导出：

```python
def auth_handler(token: int) -> tuple[bool, int]:
    ...
```

返回值是 `(判定结果, remote_id)`。返回 `(True, id)` 表示接受该客户端，
注册到 `id` 名下；`(False, _)` 表示拒绝。remote id 是管理 API 区分连接
的依据，也决定 IPv4 分配：每个用户返回**固定**的 id，重连就能保住同一个
IPv4（稳定身份）；每次返回随机 id（如 `uuid.uuid4().int`）则每次连接
都是匿名的。需要做按客户端策略、吊销、限流或日志时用它——处理器在服务端
事件循环上同步执行，要快，查找尽量在模块加载时预计算。完整 API 见
[docs/authentication.md](../docs/authentication.md)。

**伪装模式**（`--masquerade` / `WOW_MASQUERADE`）——认证失败时服务端
仍然回复一个**假成功**，然后静默丢弃该连接的所有数据包。对未认证的扫描器
来说，这个端点"开着但没用"：每次尝试都像成功，却什么都不会发生。被伪装的
连接拿到的是一次性地址，永远不会被缓存复用。

### IPv6 编址

**隧道前缀**（`--ipv6-prefix <prefix>` / `WOW_IPV6_PREFIX`，默认
`fd08::/64`）——客户端地址的分配池。默认 ULA 前缀下，客户端地址只在隧道
内有效，其流量像 IPv4 一样被 NAT66 出去；改成公网前缀（例如运营商分配的路由
`/64`）后，客户端拿到的是全球唯一的 IPv6 地址，公网上可达、也能被公网访问。
服务端自身总是占用 `network + 1`（默认即 `fd08::1`）。

**Proxy NDP**（`--ipv6-proxy-ndp` / `WOW_IPV6_PROXY_NDP`）——在物理网卡上
替每个客户端地址应答邻居发现（NDP），让发往客户端地址的回包能到达服务器。
只有当隧道前缀对服务器是 **on-link** 且**没有被路由到服务器**时才需要——
例如 AWS EC2 的 ENI 只拥有自己的单个 `/128`。如果前缀已经被路由到实例（作为
IPv6 前缀委派指派给 ENI，或通过 VPC 路由表条目指向它），AWS 会直接把流量
送到，不需要 proxy NDP。只对全局前缀有意义。

**隐私轮换**（`--ipv6-rotate-interval <n>` / `WOW_IPV6_ROTATE_INTERVAL`，
默认 `3600`）——每隔 `n` 秒给每个客户端重新分配一个随机地址，削弱其公网
IPv6 身份的长期关联性。地址是**替换**而不是新增，所以每次轮换都会断开现有
连接（相当于换了一次公网 IP）。只有全局前缀会轮换——ULA/NAT66 不会，因为
客户端本来就在 NAT 后面，轮换只会白白断连。设 `0` 关闭。

### 闲置自动关机

`--idle-script <file>`（`WOW_IDLE_SCRIPT`）导出一个 Python
`idle_callback()`；`--idle-timer <n>`（`WOW_IDLE_TIMER`，默认 `600`）是
服务端**连续无客户端**多少秒后触发该回调。典型用途：闲置云实例自动关机。

```python
# idle.py
import os

def idle_callback():
    os.system("systemctl poweroff")
```

回调在服务端事件循环上执行——要尽快返回，阻塞操作请放到子线程。回调返回后
检查会重新武装：如果回调决定不动作（例如 repair 模式守卫跳过关机），下一个
闲置周期会再次触发检查。

### 管理 API

`--api-host <addr>` / `--api-port <n>` / `--api-token <secret>` /
`--api-cors <origins>`（环境变量 `WOW_API_HOST` / `WOW_API_PORT` /
`WOW_API_TOKEN` / `WOW_API_CORS`）启用一个 FastAPI 应用，与 VPN 服务端跑在
同一个事件循环上：

- `GET /health` — 服务端存活状态
- `GET /clients` — 在线客户端（remote id、地址、对端）
- `POST /clients/{remote_id}/kick` — 踢出某个客户端
- `GET /stats` — 服务端全局计数器与配置

设置 `--api-token` 后，每个请求都必须带 `Authorization: Bearer <token>`；
token 为空时 API 完全开放，这种情况下务必只绑回环地址（默认 `127.0.0.1`）。
该 API 能踢掉在线客户端，不要随意暴露。`--api-cors`（默认 `*`）列出允许
调用 API 的浏览器来源——独立的
[wow-mgmt-dashboard](https://github.com/zaf-x/wow-mgmt-dashboard) web
面板就是用它。设 `--api-port 0` 关闭 API。

## 部署文档

完整的生产环境部署——systemd 服务、certbot TLS 证书、防火墙与安全加固——
见 [docs/deployment.zh-CN.md](../docs/deployment.zh-CN.md)
（[English](../docs/deployment.md)）。

## 安装

```bash
pip install .
```

## License

`wow-server` 采用 [MIT](https://spdx.org/licenses/MIT.html) 许可证。
