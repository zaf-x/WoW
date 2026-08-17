# WoW - Wire over Wire

[English](protocol.md) | [中文](protocol.zh-CN.md)

WoW 是一个 L3（IP 层）VPN，基于 TLS 加密的 TCP 连接传输，工作方式如下：

客户端应用 -> TUN -----TCP + TLS-----> 服务端 -> TUN -> 物理网卡

## 基础报文结构

```
0        4        5
+--------+--------+--
| Length |  Type  | Body
+--------+--------+--
```

## 报文类型

### Type 0 认证（Authentication）

```
0                     16
+----------------------+
| Authentication Token |
+----------------------+
```

### Type 1 认证响应（Authentication Response）

```
0         1                   17
+---------+-------------------+
| Success | ID (16 bytes)     |
+---------+-------------------+
```

`Success` 为 1 表示 token 被接受，为 0 表示被拒绝。`ID` 是服务端
认证处理器选定的 128-bit 连接级 id（管理 API 用它定位连接）。认证
成功后服务端紧接着发送 Type 5 IPv4 分配和 Type 6 IPv6 分配两个报文，
携带隧道地址。

### Type 2 应用数据（Application Data）

直接承载 IP 数据包。

### Type 3 Ping

无报文体。客户端周期性（每 5 秒）发送，用于穿越 NAT/防火墙中间设备
保持 TCP 连接存活，并检测死连接。

### Type 4 Pong

无报文体。服务端收到 Ping 后回复。

### Type 5 IPv4 分配（IPv4 Assign）

```
0         4     5
+---------+-----+
| IP Addr |CIDR |
+---------+-----+
```

分配给客户端 TUN 接口的虚拟 IPv4 地址（`IP Addr`，4 字节大端）与
前缀长度（`CIDR`，1 字节）。

### Type 6 IPv6 分配（IPv6 Assign）

```
0                                    16    17
+------------------------------------+-----+
| IP Addr (16 bytes)                 |CIDR |
+------------------------------------+-----+
```

分配给客户端 TUN 接口的虚拟 IPv6 地址（`IP Addr`，16 字节大端）与
前缀长度（`CIDR`，1 字节）。

握手时在认证响应之后立即发送；之后若服务端轮换客户端地址
（IPv6 隐私轮换，`--ipv6-rotate-interval`），也会随时再次发送——
客户端收到后用新地址替换其 TUN 地址。
