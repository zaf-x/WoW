# 认证（Authentication）

[English](authentication.md) | [中文](authentication.zh-CN.md)

WoW 使用共享密钥握手：客户端在 TLS 会话内发送 128-bit 认证 token，
服务端决定接受或拒绝。有两种模式：

- **token 文件**（默认）— `--token-file`（或 `WOW_TOKEN_FILE`）指向
  一个按用户区分的 token 文件。每个条目携带稳定的 remote id，因此
  同一 token 重连的客户端会拿到相同的 id——进而拿到相同的隧道地址。
- **可插拔认证** — `--auth-script auth.py` 让一个 Python 脚本自行
  决定。

## 握手流程

1. 客户端通过 TLS 连接，发送 `Authentication` 报文（协议类型 0），
   携带 128-bit token 的整数形式。
2. 服务端用该整数调用认证处理器：`auth_handler(token) -> tuple[bool, int]`。
   元组携带认证结论与**稳定的 remote id**：`(True, id)` 接受客户端
   并将其注册到 `id` 下（管理 API 用这个 id 定位连接）；`(False, _)`
   拒绝。
3. 成功时 — 服务端分配 IPv4（`10.8.0.0/24`）与 IPv6（`fd08::/64`）
   隧道地址，把客户端注册到共享的网关 TUN 上，并回复
   `AuthenticationResponse(True, id)`，随后发送 `IPv4Assign` 和
   `IPv6Assign`。**IPv4 地址按 remote id 保持稳定**：同一 id 重连会
   拿回同一个 IPv4（IPv6 仍是随机的，仅全局前缀参与隐私轮换）。
4. 失败时 — 服务端回复 `AuthenticationResponse(False, 0)`；或在
   [伪装模式](#伪装模式) 下假装成功并静默丢弃所有数据。

## token 文件

`--token-file`（或 `WOW_TOKEN_FILE`）指向一个文件，每行一个条目：

```
<token-hex> <username> <remote-id-hex>
```

- `token-hex` — 128-bit 认证 token，32 个 hex 字符（用
  `openssl rand -hex 16` 生成）。
- `username` — 自由文本标签，用于日志和管理 API。
- `remote-id-hex` — 交给服务端的稳定 128-bit id。选一个固定值
  （例如再 `openssl rand -hex 16`），让客户端重连时保持同一 id，
  从而保住隧道地址。

空行和 `#` 注释会被忽略。文件只允许 root 读取（`chmod 600`）。
删除某一行即可吊销该用户——不影响其他人。文件缺失时所有认证都会
失败，而不是让服务端崩溃。

示例 `/etc/wow/tokens.secret`：

```
3f8e1c2d...0a1b  laptop  7c21ab9e...4f0d
c0ffee00...beef  phone   deadbeef...cafe
```

## 编写认证脚本

传入 `--auth-script path/to/auth.py`（或设置 `WOW_AUTH_SCRIPT`）。
脚本在启动时加载一次，必须导出一个可调用对象：

```python
def auth_handler(token: int) -> tuple[bool, int]:
    ...
```

### 示例：静态 token 等价实现

```python
TOKEN = 0x00112233445566778899aabbccddeeff
REMOTE_ID = 0x0102030405060708090a0b0c0d0e0f10

def auth_handler(token: int) -> tuple[bool, int]:
    return token == TOKEN, REMOTE_ID
```

注意这里的 remote id 是**固定的**：返回常量让客户端获得稳定身份
（重连拿到同一 IPv4）。如果每次返回随机 id（如 `uuid.uuid4().int`），
则每次连接都是匿名的。

### 示例：带日志的允许列表

```python
ACCOUNTS = {
    0x00112233445566778899aabbccddeeff: ("laptop", 0x0102030405060708090a0b0c0d0e0f10),
    0xffeeddccbbaa99887766554433221100: ("phone", 0x102030405060708090a0b0c0d0e0f0a),
}

def auth_handler(token: int) -> tuple[bool, int]:
    entry = ACCOUNTS.get(token)
    if entry is not None:
        name, remote_id = entry
        print(f"auth: {name} connected")
        return True, remote_id
    print(f"auth: rejected token {token:032x}")
    return False, 0
```

## 注意事项

- 处理器对每个 `Authentication` 报文**在服务端事件循环上同步调用**。
  保持快速：不要阻塞、不要 `sleep`。查询表请在模块加载时预计算。
- 处理器返回的 **id** 是**稳定的按用户标识**：服务端据此派生客户端
  的 IPv4 地址，同一 id 永远拿到同一地址。它会随认证响应回传给
  客户端，管理 API（`GET /clients`、`POST /clients/{id}/kick`）用它
  定位连接。要让客户端重连后身份不变，请对同一 token 返回同一 id。
- 脚本**只在启动时导入一次**，模块级状态（token 集合、计数器）会
  跨连接保留。
- 脚本缺失、或脚本没有 `auth_handler` 属性时，服务端直接退出并报错。
- 脚本适合做按客户端策略、吊销、限流或日志。如果是静态用户列表，
  内置的 token 文件更简单。

## 伪装模式

启用 `--masquerade` 后，认证失败也会收到成功响应（客户端被告知拿到了
地址），但该连接之后的每个数据包都会被静默丢弃。对未认证的扫描器，
服务端看起来就像一个开着却无用的端口：每次尝试都像成功，却什么都不通。
