# wow-server

[![PyPI - Version](https://img.shields.io/pypi/v/wow-server.svg)](https://pypi.org/project/wow-server)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-server.svg)](https://pypi.org/project/wow-server)

[English](https://github.com/zaf-x/WoW/blob/main/wow-server/README.md) | [中文](https://github.com/zaf-x/WoW/blob/main/wow-server/README.zh-CN.md)

[WoW VPN](https://github.com/zaf-x/WoW#readme) 的服务端：接受 TLS 客户端，
使用共享 128-bit token（或自定义认证脚本）认证，为每个客户端创建 TUN
设备并对其流量做 NAT。每个客户端分配 IPv4（`10.8.0.0/24`）与 IPv6
（`fd08::/64`）隧道地址。

需要 Linux、root、`/dev/net/tun` 和 TLS 证书。

## 用法

```console
wow-server --host 0.0.0.0 --port 9999 \
           --token <32位hex> --iface eth0 \
           --cert cert.pem --key key.pem [--masquerade]
```

所有选项都可以用 `WOW_*` 环境变量设置（`WOW_HOST`、`WOW_PORT`、
`WOW_TOKEN`、`WOW_IFACE`、`WOW_CERT`、`WOW_KEY`、`WOW_SCRIPT_AUTH`、
`WOW_AUTH_SCRIPT`）。

- `--masquerade`：静默丢弃错误认证请求，不再回复
- `--script-auth --auth-script auth.py`：使用导出
  `auth_handler(token: int) -> bool` 的 Python 文件做自定义认证

## 安装

```console
pip install .
```

## License

`wow-server` 采用 [MIT](https://spdx.org/licenses/MIT.html) 许可证。
