# 部署教程

[English](deployment.md) | [中文](deployment.zh-CN.md)

本文介绍如何在 Linux VPS 上通过 systemd + Let's Encrypt 证书运行
WoW VPN 服务端，并连接客户端。

## 前置条件

- 一台 Linux VPS（Ubuntu/Debian 均可），有 root 权限，且存在
  `/dev/net/tun`：`ls -l /dev/net/tun`
- 一个指向服务器的域名（仅 Let's Encrypt 证书需要；自签名 CA 也可以）
- Python 3.10+

## 1. 安装

创建虚拟环境并安装到其中——下面的 systemd unit 会运行
`/opt/wow/venv/bin/wow-server`，所以包必须装进这个 venv
（Ubuntu/Debian 若缺少 `python3-venv`，先 `apt install python3-venv`）：

```bash
sudo mkdir -p /opt/wow
sudo python3 -m venv /opt/wow/venv
sudo /opt/wow/venv/bin/pip install wow-common wow-server
```

或从源码安装：

```bash
git clone https://github.com/zaf-x/WoW.git && cd WoW
python3 -m venv .venv && . .venv/bin/activate
pip install ./wow-common ./wow-server
```

## 2. TLS 证书

用 certbot（需要域名）：

```bash
apt install certbot
certbot certonly --standalone -d vpn.example.com
```

服务端需要 fullchain 和私钥：

```bash
ln -s /etc/letsencrypt/live/vpn.example.com/fullchain.pem /opt/wow/cert.pem
ln -s /etc/letsencrypt/live/vpn.example.com/privkey.pem  /opt/wow/key.pem
```

没有域名时，可以自建 CA 并签发服务端证书，客户端用 `-c ca.pem`
信任该 CA。

## 3. 认证 token

```bash
openssl rand -hex 16
```

客户端连接时必须出示这个 128-bit token。可插拔认证见
[authentication.md](authentication.zh-CN.md)。

## 4. 开放端口

在防火墙和云厂商安全组放行隧道端口（例如 `ufw allow 443/tcp`）。
推荐 443：隧道本身已是 TLS，监听端口与 HTTPS 无法区分。

## 5. systemd 服务

`/opt/wow/wow-server.conf`（包含 token，权限设成仅所有者可读）：

```ini
WOW_HOST_IPV4=0.0.0.0
WOW_HOST_IPV6=::
WOW_PORT=443
WOW_TOKEN=<32位hex>
WOW_IFACE=eth0
WOW_CERT=/opt/wow/cert.pem
WOW_KEY=/opt/wow/key.pem
```

同样配置也可写入 TOML 配置文件，用 `--config` 指定（见
[`templates/config.toml`](../templates/config.toml)）；优先级为
命令行参数 > TOML > 环境变量 > 默认值。

`/etc/systemd/system/wow-server.service`：

```ini
[Unit]
Description=WoW VPN server
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/wow/venv/bin/wow-server
EnvironmentFile=/opt/wow/wow-server.conf
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
chmod 600 /opt/wow/wow-server.conf
systemctl daemon-reload
systemctl enable --now wow-server
```

> `WOW_IFACE` 必须是物理出网网卡（用 `ip route get 1.1.1.1` 查看）。
> 服务端会创建一张所有客户端共用的网关 TUN 设备（`wowgateway`），
> 开启 IPv4/IPv6 转发，并在该网卡上配置 iptables/ip6tables
> MASQUERADE。若内核不支持 IPv6 NAT，隧道内的 IPv6 互通不受影响，
> 只是无法通过 NAT66 上网。

## 6. 验证服务端

```bash
systemctl status wow-server
ss -tlnp | grep 443
journalctl -u wow-server -f
```

应能看到 `Server listening on 0.0.0.0:443`。

## 7. 连接客户端

在需要 root（TUN 设备 + 延迟探测用的原始 ICMP socket）的 Linux 机器上：

```bash
pip install wow-common wow-client

# 存成命名配置，再交互式启动
sudo wow-client save myvpn -s vpn.example.com -p 443 -t <32位hex>
sudo wow-client launch
```

或直接连接：

```bash
sudo wow-client start -s vpn.example.com -p 443 -t <32位hex>
```

> 若 `sudo` 提示 `wow-client: command not found`，说明可执行文件不在
> sudo 的 PATH 里（例如 pipx 或 `--user` 装到了 `~/.local/bin`）——
> 改用 `sudo "$(which wow-client)" ...`。

## 8. 测试隧道

状态面板会显示分配的地址（`10.8.0.x/24` 和 `fd08::x/64`）。隧道建立后：

```bash
ping 10.8.0.1                # IPv4 连通服务端
ping -6 fd08::1              # IPv6 连通服务端
curl -4 https://api.ipify.org   # 经隧道的公网 IPv4
curl -6 https://api6.ipify.org  # 经隧道的公网 IPv6
```

客户端在共享网关 TUN 上按扁平地址分配：第 N 个客户端拿到
`10.8.0.(N+1)/24` 和 `prefix::(N+1)`（第 1 个客户端即 `10.8.0.2` /
`fd08::2`；网关本身是 `10.8.0.1` / `fd08::1`）。

## 9. 公网 IPv6（可选）

默认客户端拿到的是 ULA IPv6（`fd08::/64`），和 IPv4 一样走 NAT。想让
客户端拿到**全局 IPv6 地址**，把隧道网络指向提供商路由到本机的公网
前缀即可：

```ini
WOW_IPV6_PREFIX=2001:db8:1:2::/64
```

（或用命令行参数 `--ipv6-prefix`）。此时 NAT66 会自动关闭，客户端以
自己的全局地址访问公网——真正的端到端 IPv6，没有 NAT。

> `2001:db8::/32` 是 RFC 3849 的文档保留段，仅作占位示例——请换成
> 提供商给你的真实公网前缀。非全局前缀（ULA、文档段）NAT66 保持
> 开启，只有真正可路由的段才会自动关闭。

按提供商情况分两种：

- **路由前缀**（大多数 VPS 的"附加 IPv6"段）：无需额外配置——服务端
  直接把前缀从物理网卡转发出去。
- **链路前缀**（如 AWS EC2）：内核需要为客户端地址应答 NDP。开启
  `--ipv6-proxy-ndp`（或 `WOW_IPV6_PROXY_NDP=1`），服务端会自动为每个
  客户端添加 proxy NDP 条目。另外必须在 AWS 控制台**关闭实例网卡的
  源/目标检查**（EC2 控制台 → 网络接口 → 更改源/目标检查 → 禁用），
  否则虚拟化层会丢弃转发的客户端流量。

然后从另一台主机 ping 客户端地址验证。

## 10. 安全加固

- 加 `--masquerade`（在 unit 的 `ExecStart` 行末尾追加，例如
  `ExecStart=/opt/wow/venv/bin/wow-server --masquerade`）：认证失败
  时回复假成功并静默丢弃其流量，而不是明确拒绝，对扫描器表现为
  "开着但无用"的端口。
- 需要按客户端做策略、限流或日志时，用
  `--script-auth --auth-script auth.py`。
- 防火墙只放行隧道端口，其余端口不需要对外暴露。
