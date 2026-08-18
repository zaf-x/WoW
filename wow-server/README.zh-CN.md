# wow-server

[![PyPI - Version](https://img.shields.io/pypi/v/wow-server.svg)](https://pypi.org/project/wow-server)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-server.svg)](https://pypi.org/project/wow-server)

[English](https://github.com/zaf-x/WoW/blob/main/wow-server/README.md) | [中文](https://github.com/zaf-x/WoW/blob/main/wow-server/README.zh-CN.md)

[WoW VPN](https://github.com/zaf-x/WoW#readme) 的服务端：接受 TLS 客户端，
使用 token 文件（或自定义认证脚本）认证，创建一张网关 TUN
设备（每台服务器一张，所有客户端共用）并对其流量做 NAT。每个客户端分配 IPv4（`10.8.0.0/24`）与一个 IPv6
隧道地址——默认 ULA `fd08::/64`，也可用 `--ipv6-prefix` /
`WOW_IPV6_PREFIX` 配公网前缀，让客户端拿到全局 IPv6。

需要 Linux、root、`/dev/net/tun` 和 TLS 证书。

## 用法

```bash
wow-server --host-ipv4 0.0.0.0 --host-ipv6 :: --port 9999 \
           --token-file /etc/wow/tokens.secret --iface eth0 \
           --cert cert.pem --key key.pem [--masquerade]
```

选项也可以通过 `WOW_*` 环境变量或可选的 TOML 配置文件设置（`--config`，
模板见 [`templates/config.toml`](../../templates/config.toml)）；优先级为
命令行参数 > TOML > 环境变量 > 默认值。环境变量有
（`WOW_HOST_IPV4`、`WOW_HOST_IPV6`、`WOW_PORT`、`WOW_TOKEN_FILE`、
`WOW_IFACE`、`WOW_CERT`、`WOW_KEY`、`WOW_IPV6_PREFIX`、
`WOW_IPV6_PROXY_NDP`、`WOW_AUTH_SCRIPT`、
`WOW_MASQUERADE`、`WOW_IDLE_SCRIPT`、`WOW_IDLE_TIMER`、
`WOW_IPV6_ROTATE_INTERVAL`、`WOW_API_HOST`、`WOW_API_PORT`、
`WOW_API_TOKEN`、`WOW_VERBOSE`）。

- `--token-file /etc/wow/tokens.secret`：默认认证方式——每行一条
  `<token-hex> <username> <remote-id-hex>`。remote id 是稳定的，因此
  同一 token 重连的客户端会保住同一个 IPv4 地址（删除某行即吊销该用户）
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

## 安装

```bash
pip install .
```

## License

`wow-server` 采用 [MIT](https://spdx.org/licenses/MIT.html) 许可证。
