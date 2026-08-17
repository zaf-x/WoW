# 认证（Authentication）

[English](authentication.md) | [中文](authentication.zh-CN.md)

WoW 使用共享密钥握手：客户端在 TLS 会话内发送 128-bit 认证 token，
服务端决定接受或拒绝。有两种模式：

- **静态 token**（默认）— 通过命令行传入的 token（`--token` /
  `WOW_TOKEN`）。
- **可插拔认证** — `--script-auth --auth-script auth.py` 让一个
  Python 脚本自行决定。

## 握手流程

1. 客户端通过 TLS 连接，发送 `Authentication` 报文（协议类型 0），
   携带 128-bit token 的整数形式。
2. 服务端用该整数调用认证处理器：`auth_handler(token) -> tuple[bool, int]`。
   元组携带认证结论与连接 id：`(True, id)` 接受客户端并将其注册到
   `id` 下（管理 API 用这个 id 定位连接）；`(False, _)` 拒绝。
3. 成功时 — 服务端分配 IPv4（`10.8.0.0/24`）与 IPv6（`fd08::/64`）
   隧道地址，把客户端注册到共享的网关 TUN 上，并回复
   `AuthenticationResponse(True, id)`，随后发送 `IPv4Assign` 和
   `IPv6Assign`。
4. 失败时 — 服务端回复 `AuthenticationResponse(False, 0)`；或在
   [伪装模式](#伪装模式) 下假装成功并静默丢弃所有数据。

## 编写认证脚本

传入 `--script-auth --auth-script path/to/auth.py`（或设置
`WOW_SCRIPT_AUTH=1` 和 `WOW_AUTH_SCRIPT`）。脚本在启动时加载一次，
必须导出一个可调用对象：

```python
def auth_handler(token: int) -> tuple[bool, int]:
    ...
```

### 示例：静态 token 等价实现

```python
import uuid

TOKEN = 0x00112233445566778899aabbccddeeff

def auth_handler(token: int) -> tuple[bool, int]:
    return token == TOKEN, uuid.uuid4().int
```

### 示例：带日志的允许列表

```python
import uuid

ALLOWED = {
    0x00112233445566778899aabbccddeeff: "laptop",
    0xffeeddccbbaa99887766554433221100: "phone",
}

def auth_handler(token: int) -> tuple[bool, int]:
    name = ALLOWED.get(token)
    if name is not None:
        print(f"auth: {name} connected")
        return True, uuid.uuid4().int
    print(f"auth: rejected token {token:032x}")
    return False, 0
```

## 注意事项

- 处理器对每个 `Authentication` 报文**在服务端事件循环上同步调用**。
  保持快速：不要阻塞、不要 `sleep`。查询表请在模块加载时预计算。
- 处理器返回的 **id** 是连接级标识（例如 `uuid.uuid4().int`），会随
  认证响应回传给客户端，管理 API（`GET /clients`、
  `POST /clients/{id}/kick`）用它定位连接。
- 脚本**只在启动时导入一次**，模块级状态（token 集合、计数器）会
  跨连接保留。
- 脚本缺失、或脚本没有 `auth_handler` 属性时，服务端直接退出并报错。
- 脚本适合做按客户端策略、吊销、限流或日志。如果只有一个共享密钥，
  内置的 `--token` 更简单。

## 伪装模式

启用 `--masquerade` 后，认证失败也会收到成功响应（客户端被告知拿到了
地址），但该连接之后的每个数据包都会被静默丢弃。对未认证的扫描器，
服务端看起来就像一个开着却无用的端口：每次尝试都像成功，却什么都不通。
