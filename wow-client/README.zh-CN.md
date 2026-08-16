# wow-client

[![PyPI - Version](https://img.shields.io/pypi/v/wow-client.svg)](https://pypi.org/project/wow-client)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/wow-client.svg)](https://pypi.org/project/wow-client)

[English](https://github.com/zaf-x/WoW/blob/main/wow-client/README.md) | [中文](https://github.com/zaf-x/WoW/blob/main/wow-client/README.zh-CN.md)

[WoW VPN](https://github.com/zaf-x/WoW#readme) 的客户端：通过 TLS 连接服务端，
使用 128-bit token 认证，创建本地 TUN 设备并把流量导入隧道。实时状态面板
显示上下行速率与客户端↔服务端 / 客户端↔公网延迟。

需要 Linux 和 root（TUN 设备 + 延迟探测用的原始 ICMP socket）。

## 用法

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

配置文件存放在 `$XDG_CONFIG_HOME/wow-client/config.json`
（默认 `~/.config/wow-client/config.json`），仅所有者可读。

## 安装

```bash
pip install .
```

## License

`wow-client` 采用 [MIT](https://spdx.org/licenses/MIT.html) 许可证。
