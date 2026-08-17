# Authentication

[English](authentication.md) | [中文](authentication.zh-CN.md)

WoW uses a shared-secret handshake: the client sends a 128-bit
authentication token inside the TLS session, and the server decides to
accept or reject it. Two modes are available:

- **Static token** — the default: the token passed on the command line
  (`--token` / `WOW_TOKEN`).
- **Pluggable authentication** — `--script-auth --auth-script auth.py`
  lets a Python script make the decision instead.

## How the handshake works

1. The client connects over TLS and sends an `Authentication` packet
   (protocol type 0) carrying the 128-bit token as an integer.
2. The server calls its auth handler with that integer:
   `auth_handler(token) -> tuple[bool, int]`. The tuple carries the
   verdict and a per-connection id: `(True, id)` accepts the client and
   registers it under `id` (the management API addresses connections by
   this id); `(False, _)` rejects it.
3. On success — the server assigns IPv4 (`10.8.0.0/24`) and IPv6
   (`fd08::/64`) tunnel addresses, registers the client on the shared
   gateway TUN, and replies with `AuthenticationResponse(True, id)`
   followed by `IPv4Assign` and `IPv6Assign`.
4. On failure — the server replies `AuthenticationResponse(False, 0)`,
   or pretends to succeed and silently drops everything in
   [masquerade mode](#masquerade-mode).

## Writing an auth script

Pass `--script-auth --auth-script path/to/auth.py` (or set
`WOW_SCRIPT_AUTH=1` and `WOW_AUTH_SCRIPT`). The file is loaded once at
startup and must export a callable:

```python
def auth_handler(token: int) -> tuple[bool, int]:
    ...
```

### Example: static token equivalent

```python
import uuid

TOKEN = 0x00112233445566778899aabbccddeeff

def auth_handler(token: int) -> tuple[bool, int]:
    return token == TOKEN, uuid.uuid4().int
```

### Example: allowlist with logging

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

## Notes

- The handler is called **synchronously on the server's event loop** for
  every `Authentication` packet. Keep it fast: no blocking calls, no
  `sleep`. Precompute lookups at module load time.
- The **id** returned by the handler is a per-connection identifier
  (e.g. `uuid.uuid4().int`). It is echoed to the client in the
  authentication response and used by the management API
  (`GET /clients`, `POST /clients/{id}/kick`).
- The script is imported **once at startup**, so module-level state
  (token sets, counters) persists across connections.
- A missing script, or a script without an `auth_handler` attribute,
  makes the server exit with an error.
- Use the script for per-client policy, revocation, rate limiting or
  logging. For a single shared secret the built-in `--token` is simpler.

## Masquerade mode

With `--masquerade`, a failed authentication is still answered with a
success response (the client is told it got an address), but every
packet from that connection is then silently dropped. To an
unauthenticated scanner the server looks like a live but useless
endpoint: every attempt appears to succeed and nothing ever works.
