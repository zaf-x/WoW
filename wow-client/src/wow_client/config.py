"""Saved profile support for the WoW VPN client.

Profiles are stored as JSON under a top-level ``"profiles"`` object keyed
by profile name, in ``$XDG_CONFIG_HOME/wow-client/config.json`` (or
``~/.config/wow-client/config.json``)::

    {
      "profiles": {
        "my-server": {
          "host": "vpn.example.com",
          "port": 443,
          "token": "00112233445566778899aabbccddeeff",
          "ca_cert": "/path/to/ca.pem"
        }
      }
    }
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "wow-client"
    / "config.json"
)


@dataclass
class Profile:
    """A saved server configuration.

    Attributes:
        host: VPN server hostname or address.
        port: VPN server port.
        token: 128-bit authentication token as a hex string.
        ca_cert: Path to a PEM CA certificate file to trust for verifying
            the server, or None to use the system default CA bundle.
    """

    host: str
    port: int
    token: str
    ca_cert: str | None = None


def load_profiles(path: Path = CONFIG_PATH) -> dict[str, Profile]:
    """Load saved profiles from the config file.

    Args:
        path: Path to the JSON config file.

    Returns:
        A mapping of profile name to :class:`Profile`. An empty mapping is
        returned when the file does not exist.

    Raises:
        ValueError: If the file is not valid JSON or a profile is missing
            a required field.
    """
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc

    profiles: dict[str, Profile] = {}
    for name, entry in raw.get("profiles", {}).items():
        try:
            profiles[name] = Profile(
                host=entry["host"],
                port=int(entry["port"]),
                token=entry["token"],
                ca_cert=entry.get("ca_cert"),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(
                f"{path}: profile {name!r} is missing a required field: {exc}"
            ) from exc
    return profiles


def save_profile(name: str, profile: Profile, path: Path = CONFIG_PATH):
    """Add or replace a profile in the config file.

    Creates the config file (and its parent directory) when needed, keeps
    any other saved profiles, and restricts the file permissions to the
    owner since it contains tokens.

    Args:
        name: Profile name.
        profile: The profile to save.
        path: Path to the JSON config file.

    Raises:
        ValueError: If the file exists but is not valid JSON.
    """
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    else:
        raw = {}

    raw.setdefault("profiles", {})[name] = { # type: ignore
        "host": profile.host,
        "port": profile.port,
        "token": profile.token,
        "ca_cert": profile.ca_cert,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
