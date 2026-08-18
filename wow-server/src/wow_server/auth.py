"""Default token-file authenticator for wow-server.

The token file maps each 128-bit token to a username and a stable
remote id, one entry per line::

    <token-hex> <username> <remote-id-hex>

- ``token-hex``: the 128-bit auth token as 32 hex chars.
- ``username``: a free-form label (shown in logs / the management API).
- ``remote-id-hex``: the stable 128-bit id handed to the server, so a
  client reconnecting with the same token keeps the same remote id —
  and thus the same tunnel addresses.

Blank lines and lines starting with ``#`` are ignored. Keep the file
readable only by root (``chmod 600``); a missing file makes every
authentication fail rather than crashing the server.
"""

import uuid
from pathlib import Path

class Auth:
    """Token-file authenticator: ``(token) -> (ok, remote_id)``.

    Args:
        token_file: Path to the token file. ``None`` or a missing file
            means every authentication fails (with a random id, so a
            client cannot tell it apart from masquerade).
    """

    def __init__(self, token_file: str | None = None):
        self.token_file = token_file
        self.passwd: dict[int, tuple[str, int]] = {}
        self.load()

    def load(self) -> None:
        """Read ``token_file`` into :attr:`passwd`.

        Missing file, blank lines and ``#`` comments are handled
        gracefully; malformed lines are skipped with an error message.
        """
        if not self.token_file:
            return
        path = Path(self.token_file)
        if not path.is_file():
            print(f"E: token file not found: {self.token_file}")
            return
        with path.open("r") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) != 3:
                    print(f"E: {self.token_file}:{lineno}: expected "
                          f"'<token-hex> <username> <remote-id-hex>', got: {line}")
                    continue
                try:
                    token = int(parts[0], 16)
                    remote_id = int(parts[2], 16)
                except ValueError:
                    print(f"E: {self.token_file}:{lineno}: bad hex value: {line}")
                    continue
                self.passwd[token] = (parts[1], remote_id)

    def auth(self, token: int) -> tuple[bool, int]:
        """Authenticate ``token``: ``(ok, remote_id)``.

        Failed lookups return a random remote id so a masquerading
        server (which answers with a fake success and its own id) is
        indistinguishable from a real one to probing clients.
        """
        entry = self.passwd.get(token)
        if entry is None:
            return (False, uuid.uuid4().int)
        return (True, entry[1])

    def __call__(self, token: int) -> tuple[bool, int]:
        return self.auth(token)
