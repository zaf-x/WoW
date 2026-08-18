# Authentication

[English](authentication.md) | [中文](authentication.zh-CN.md)

WoW uses a shared-secret handshake: the client sends a 128-bit
authentication token inside the TLS session, and the server decides to
accept or reject it. Two modes are available:

- **Token file** — the default: `--token-file` (or `WOW_TOKEN_FILE`)
  points at a file of per-user tokens. Each entry carries a stable
  remote id, so a client reconnecting with the same token keeps the
  same id — and therefore the same tunnel addresses.
- **Pluggable authentication** — `--auth-script auth.py` lets a Python
  script make the decision instead.

## How the handshake works

1. The client connects over TLS and sends an `Authentication` packet
   (protocol type 0) carrying the 128-bit token as an integer.
2. The server calls its auth handler with that integer:
   `auth_handler(token) -> tuple[bool, int]`. The tuple carries the
   verdict and a **stable remote id**: `(True, id)` accepts the client
   and registers it under `id` (the management API addresses
   connections by this id); `(False, _)` rejects it.
3. On success — the server assigns IPv4 (`10.8.0.0/24`) and IPv6
   (`fd08::/64`) tunnel addresses, registers the client on the shared
   gateway TUN, and replies with `AuthenticationResponse(True, id)`
   followed by `IPv4Assign` and `IPv6Assign`. The **IPv4 address is
   stable per remote id**: reconnecting with the same id gets the same
   IPv4 back (IPv6 stays random, and rotates for privacy on global
   prefixes).
4. On failure — the server replies `AuthenticationResponse(False, 0)`,
   or pretends to succeed and silently drops everything in
   [masquerade mode](#masquerade-mode).

## Token file

`--token-file` (or `WOW_TOKEN_FILE`) points to a file with one entry
per line:

```
<token-hex> <username> <remote-id-hex>
```

- `token-hex` — the 128-bit auth token as 32 hex chars (generate with
  `openssl rand -hex 16`).
- `username` — a free-form label for logs and the management API.
- `remote-id-hex` — the stable 128-bit id handed to the server. Pick a
  fixed value (e.g. another `openssl rand -hex 16`) so the client
  reconnects with the same id and keeps its tunnel addresses.

Blank lines and `#` comments are ignored. Keep the file readable only
by root (`chmod 600`). Revoke a user by deleting their line — nobody
else is affected. A missing file makes every authentication fail
rather than crashing the server.

Example `/etc/wow/tokens.secret`:

```
3f8e1c2d...0a1b  laptop  7c21ab9e...4f0d
c0ffee00...beef  phone   deadbeef...cafe
```

## Writing an auth script

Pass `--auth-script path/to/auth.py` (or set `WOW_AUTH_SCRIPT`). The
file is loaded once at startup and must export a callable:

```python
def auth_handler(token: int) -> tuple[bool, int]:
    ...
```

### Example: static token equivalent

```python
TOKEN = 0x00112233445566778899aabbccddeeff
REMOTE_ID = 0x0102030405060708090a0b0c0d0e0f10

def auth_handler(token: int) -> tuple[bool, int]:
    return token == TOKEN, REMOTE_ID
```

Note the **fixed** remote id: returning a constant gives the client a
stable identity (same IPv4 on reconnect). Returning a fresh random id
(e.g. `uuid.uuid4().int`) makes every connection anonymous instead.

### Example: allowlist with logging

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

## Notes

- The handler is called **synchronously on the server's event loop** for
  every `Authentication` packet. Keep it fast: no blocking calls, no
  `sleep`. Precompute lookups at module load time.
- The **id** returned by the handler is a **stable per-user
  identifier**: the server derives the client's IPv4 address from it,
  so the same id always gets the same address. It is echoed to the
  client in the authentication response and used by the management API
  (`GET /clients`, `POST /clients/{id}/kick`). To keep a client's
  identity across reconnects, return the same id for the same token.
- The script is imported **once at startup**, so module-level state
  (token sets, counters) persists across connections.
- A missing script, or a script without an `auth_handler` attribute,
  makes the server exit with an error.
- Use the script for per-client policy, revocation, rate limiting or
  logging. For a static user list the built-in token file is simpler.

## Masquerade mode

With `--masquerade`, a failed authentication is still answered with a
success response (the client is told it got an address), but every
packet from that connection is then silently dropped. To an
unauthenticated scanner the server looks like a live but useless
endpoint: every attempt appears to succeed and nothing ever works.
