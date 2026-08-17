# wow-server

[![PyPI - Version](https://img.shields.io/pypi/v/wow-server.svg)](https://pypi.org/project/wow-server)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-server.svg)](https://pypi.org/project/wow-server)

[English](https://github.com/zaf-x/WoW/blob/main/wow-server/README.md) | [中文](https://github.com/zaf-x/WoW/blob/main/wow-server/README.zh-CN.md)

[WoW VPN](https://github.com/zaf-x/WoW#readme) 的服务端：接受 TLS 客户端，
使用共享 128-bit token（或自定义认证脚本）认证，创建一张网关 TUN
设备（每台服务器一张，所有客户端共用）并对其流量做 NAT。每个客户端分配 IPv4（`10.8.0.0/24`）与一个 IPv6
隧道地址——默认 ULA `fd08::/64`，也可用 `--ipv6-prefix` /
`WOW_IPV6_PREFIX` 配公网前缀，让客户端拿到全局 IPv6。

需要 Linux、root、`/dev/net/tun` 和 TLS 证书。

## 用法

```bash
wow-server --host 0.0.0.0 --port 9999 \
           --token <32位hex> --iface eth0 \
           --cert cert.pem --key key.pem [--masquerade]
```

大多数选项都可以用 `WOW_*` 环境变量设置（`WOW_HOST`、`WOW_PORT`、
`WOW_TOKEN`、`WOW_IFACE`、`WOW_CERT`、`WOW_KEY`、`WOW_IPV6_PREFIX`、
`WOW_IPV6_PROXY_NDP`、`WOW_SCRIPT_AUTH`、`WOW_AUTH_SCRIPT`、
`WOW_IDLE_SCRIPT`、`WOW_IDLE_TIMER`、`WOW_IPV6_ROTATE_INTERVAL`）；
`--masquerade` 与 `--verbose` 仅支持命令行。

- `--masquerade`：对错误认证回复假成功，随后静默丢弃其流量
- `--script-auth --auth-script auth.py`：使用导出
  `auth_handler(token: int) -> bool` 的 Python 文件做自定义认证
- `--idle-script idle.py --idle-timer 600`：当服务端在指定秒数内没有
  任何客户端时，运行 Python 文件里的 `idle_callback()`——例如闲置实例
  自动关机
- `--ipv6-rotate-interval 3600`：每隔指定秒数为每个客户端从隧道前缀
  重新分配一个随机 IPv6 地址（隐私轮换；默认 1 小时，0 关闭）。地址
  更换会断开现有连接，相当于换了一次公网 IP。

## 安装

```bash
pip install .
```

## License

`wow-server` 采用 [MIT](https://spdx.org/licenses/MIT.html) 许可证。
