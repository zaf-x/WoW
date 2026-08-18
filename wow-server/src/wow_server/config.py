"""Configuration: merge TOML, environment variables and CLI flags.

Every setting is resolved with the same precedence:

    command-line flag  >  TOML config file  >  ``WOW_*`` environment variable
    >  built-in default

The TOML file is optional: when it is missing, configuration falls back to
environment variables and CLI flags alone (matching pre-0.1 deployments).
"""

import argparse
import importlib.util
import os
import uuid
from types import ModuleType
from typing import Any, Callable

import tomlkit

DEFAULT_CONFIG_PATH = "/etc/wow/config.toml"

_args: argparse.Namespace | None = None


def parse_args() -> argparse.Namespace:
    """Parse command-line flags, falling back to nothing (merged later).

    Unlike the CLI itself, no defaults are applied here: every option
    defaults to ``None`` so :class:`Config` can tell "flag not given"
    apart from an explicit value, and resolve it against the TOML file
    and environment variables. The result is cached.

    Returns:
        The parsed arguments namespace.
    """
    global _args
    if _args is not None:
        return _args
    parser = argparse.ArgumentParser(prog="wow-server", description="WoW VPN server")
    parser.add_argument("--config", default=None,
                        help=f"path to the TOML config file "
                             f"(default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--host-ipv4", default=None,
                        help="IPv4 listen address (default: 0.0.0.0, env WOW_HOST_IPV4)")
    parser.add_argument("--host-ipv6", default=None,
                        help="IPv6 listen address, empty disables (default: ::, env WOW_HOST_IPV6)")
    parser.add_argument("--port", type=int, default=None,
                        help="listen port (default: 9999, env WOW_PORT)")
    parser.add_argument("--iface", default=None,
                        help="physical interface for NAT, e.g. ens5 (env WOW_IFACE)")
    parser.add_argument("--cert", default=None,
                        help="TLS certificate file (env WOW_CERT)")
    parser.add_argument("--key", default=None,
                        help="TLS private key file (env WOW_KEY)")
    parser.add_argument("--script-auth", action="store_true", default=None,
                        help="use a python script for authentication (env WOW_SCRIPT_AUTH)")
    parser.add_argument("--auth-script", default=None,
                        help="file exporting auth_handler() (env WOW_AUTH_SCRIPT)")
    parser.add_argument("--token", default=None,
                        help="128-bit auth token as 32 hex chars (env WOW_TOKEN)")
    parser.add_argument("--masquerade", action="store_true", default=None,
                        help="reply to bad auth with a fake success, then drop their traffic "
                             "(env WOW_MASQUERADE)")
    parser.add_argument("--idle-script", default=None,
                        help="python file exporting idle_callback(), run after the server has "
                             "had no clients for --idle-timer seconds (env WOW_IDLE_SCRIPT)")
    parser.add_argument("--idle-timer", type=int, default=None,
                        help="seconds without clients before idle_callback() fires "
                             "(default: 600, env WOW_IDLE_TIMER)")
    parser.add_argument("--ipv6-prefix", default=None,
                        help="IPv6 tunnel network (default: fd08::/64, env WOW_IPV6_PREFIX)")
    parser.add_argument("--ipv6-proxy-ndp", action="store_true", default=None,
                        help="proxy-NDP for client IPv6 addresses on the egress interface "
                             "(needed for on-link prefixes like AWS EC2, env WOW_IPV6_PROXY_NDP)")
    parser.add_argument("--ipv6-rotate-interval", type=int, default=None,
                        help="seconds between reassigning each client a new random IPv6 "
                             "address (privacy rotation; 0 disables, default: 3600, "
                             "env WOW_IPV6_ROTATE_INTERVAL)")
    parser.add_argument("--api-host", default=None,
                        help="management API bind address (default: 127.0.0.1, env WOW_API_HOST)")
    parser.add_argument("--api-port", type=int, default=None,
                        help="management API port, 0 disables (default: 8000, env WOW_API_PORT)")
    parser.add_argument("--api-token", default=None,
                        help="bearer token for the management API; empty means no auth "
                             "(env WOW_API_TOKEN)")
    parser.add_argument("-v", "--verbose", action="store_true", default=None,
                        help="debug logging (env WOW_VERBOSE)")
    _args = parser.parse_args()
    return _args


def _resolve(cli: Any, toml: Any, env: str | None, default: Any,
             convert: Callable[[str], Any] = str) -> Any:
    """Pick the first present value: CLI flag > TOML > env > default.

    ``cli`` and ``env`` are used as-is when not None; the env string is
    converted with ``convert`` (``str`` by default). TOML values are
    normalized to plain Python types — tomlkit returns str/int/bool
    subclasses that carry trivia metadata and can break consumers that
    embed them into code objects or bytes (e.g. ``co_filename``).
    """
    if cli is not None:
        return cli
    if toml is not None:
        if isinstance(toml, str):
            return str(toml)
        if isinstance(toml, bool):  # before int: bool is an int subclass
            return bool(toml)
        if isinstance(toml, int):
            return int(toml)
        return toml
    if env is not None:
        return convert(env)
    return default


def _env_bool(value: str) -> bool:
    """Parse a boolean env value with the existing ``0``/``1`` convention."""
    return bool(int(value))


class Config:
    """Layered server configuration backed by an optional TOML file.

    Attributes:
        config_file_path: Path of the TOML config file (may not exist;
            then it is treated as an empty document).
        toml: The parsed TOML document, set by :meth:`load`.
    """

    def __init__(self, config_file_path: str | None = None):
        """Initialize the config, defaulting to ``/etc/wow/config.toml``.

        Args:
            config_file_path: Path of the TOML config file, or None for
                the default location.
        """
        self.config_file_path = config_file_path or DEFAULT_CONFIG_PATH
        self.toml: tomlkit.TOMLDocument | None = None

    def load(self) -> None:
        """Parse the TOML config file; a missing file behaves as an empty document."""
        if os.path.isfile(self.config_file_path):
            with open(self.config_file_path, "r", encoding="utf-8") as f:
                self.toml = tomlkit.parse(f.read())
        else:
            self.toml = tomlkit.parse("")

    def dump(self) -> None:
        """Write the current TOML document back to ``config_file_path``."""
        if self.toml is None:
            raise TypeError("TOML not loaded yet")
        with open(self.config_file_path, "w", encoding="utf-8") as f:
            f.write(tomlkit.dumps(self.toml))

    def _load_pluggable_script(self, script_path: str) -> ModuleType:
        """Import a Python file and return the loaded module."""
        module_name = os.path.splitext(os.path.basename(script_path))[0]
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            print("E: invalid script: import failed")
            exit(1)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def get_kwargs(self) -> dict[str, Any]:
        """Build the keyword arguments for :class:`wow_server.server.Server`.

        Every setting is resolved with precedence CLI flag > TOML > env >
        built-in default; pluggable auth/idle scripts are loaded when
        configured.

        Returns:
            A dict suitable for ``Server(**config.get_kwargs())``.

        Raises:
            TypeError: If :meth:`load` was not called first.
            SystemExit: If a required setting is missing everywhere, a
                pluggable script is invalid, or the token is not hex.
        """
        if self.toml is None:
            raise TypeError("TOML not loaded yet")
        args = parse_args()
        toml = self.toml

        def _get(section: str, cli_key: str, toml_key: str, env: str, default: Any,
                 convert: Callable[[str], Any] = str) -> Any:
            table = toml.get(section) # type: ignore
            toml_val = table.get(toml_key) if table is not None else None # type: ignore
            return _resolve(getattr(args, cli_key, None), toml_val,
                            os.environ.get(env), default, convert)

        host_ipv4 = _get("network", "host_ipv4", "host_ipv4", "WOW_HOST_IPV4", "0.0.0.0")
        host_ipv6 = _get("network", "host_ipv6", "host_ipv6", "WOW_HOST_IPV6", "::")
        port = _get("network", "port", "port", "WOW_PORT", 9999, int)
        interface = _get("network", "iface", "interface", "WOW_IFACE", None)
        ipv6_prefix = _get("network", "ipv6_prefix", "ipv6_prefix", "WOW_IPV6_PREFIX", "fd08::/64")
        proxy_ndp = _get("network", "ipv6_proxy_ndp", "ipv6_proxy_ndp", "WOW_IPV6_PROXY_NDP", False, _env_bool)
        ipv6_rotate_interval = _get("network", "ipv6_rotate_interval",
                                    "ipv6_rotate_interval",
                                    "WOW_IPV6_ROTATE_INTERVAL", 3600, int)
        cert = _get("tls", "cert", "cert", "WOW_CERT", None)
        key = _get("tls", "key", "key", "WOW_KEY", None)
        masquerade = _get("auth", "masquerade", "masquerade", "WOW_MASQUERADE", False, _env_bool)

        auth_table = self.toml.get("auth") # type: ignore
        script_auth = _resolve(
            args.script_auth,
            bool(auth_table.get("script")) if auth_table is not None else None, # type: ignore
            os.environ.get("WOW_SCRIPT_AUTH"), False, _env_bool,
        )
        auth_script = _resolve(
            args.auth_script,
            auth_table.get("script") if auth_table is not None else None, #type: ignore
            os.environ.get("WOW_AUTH_SCRIPT"), None,
        )
        token_hex = _resolve(
            args.token,
            auth_table.get("token") if auth_table is not None else None,# type: ignore
            os.environ.get("WOW_TOKEN"), None,
        )

        idle_table = self.toml.get("idle") # type: ignore
        idle_script = _resolve(
            args.idle_script,
            idle_table.get("script") if idle_table is not None else None, # type: ignore
            os.environ.get("WOW_IDLE_SCRIPT"), None,
        )
        idle_timer = _get("idle", "idle_timer", "timer", "WOW_IDLE_TIMER", 600, int)

        # Required settings: every layer must be absent for these to fire.
        missing = [
            name for name, value in (
                ("interface", interface), ("cert", cert), ("key", key),
            ) if not value
        ]
        if not script_auth and not token_hex:
            missing.append("token")
        if missing:
            print("E: required setting(s) missing: " + ", ".join(missing))
            print("   provide them via CLI flag, the TOML config file, or WOW_* env vars")
            exit(1)

        if script_auth:
            if not auth_script:
                print("Must give auth script when using script auth")
                exit(1)
            module = self._load_pluggable_script(auth_script)
            try:
                auth_handler = module.auth_handler
            except AttributeError:
                print("E: invalid script: must provide `auth_handler` function")
                exit(1)
        else:
            try:
                token = int(token_hex, 16)
            except (TypeError, ValueError):
                print("E: --token must be a hex string")
                exit(1)
            auth_handler: Callable[[int], tuple[bool, int]] = lambda x: (x == token, uuid.uuid4().int)

        idle_callback: Callable[[], None] | None = None
        if idle_script:
            module = self._load_pluggable_script(idle_script)
            try:
                idle_callback = module.idle_callback
            except AttributeError:
                print("E: invalid script: must provide `idle_callback` function")
                exit(1)

        return {
            "host_ipv4": host_ipv4,
            "host_ipv6": host_ipv6,
            "port": port,
            "interface": interface,
            "auth_handler": auth_handler,
            "cert": cert,
            "key": key,
            "ipv6_prefix": ipv6_prefix,
            "proxy_ndp": proxy_ndp,
            "ipv6_rotate_interval": ipv6_rotate_interval,
            "masquerade": masquerade,
            "idle_callback": idle_callback,
            "idle_timer": idle_timer,
        }

    def get_api_kwargs(self) -> dict[str, Any]:
        """Build the keyword arguments for the management API (uvicorn + FastAPI)."""
        if self.toml is None:
            raise TypeError("TOML not loaded yet")
        args = parse_args()
        api_table = self.toml.get("api") # type: ignore

        def _get(cli_key: str, toml_key: str, env: str, default: Any,
                 convert: Callable[[str], Any] = str) -> Any:
            toml_val = api_table.get(toml_key) if api_table is not None else None # type: ignore
            return _resolve(getattr(args, cli_key, None), toml_val,
                            os.environ.get(env), default, convert)

        return {
            "host": _get("api_host", "host", "WOW_API_HOST", "127.0.0.1"),
            "port": _get("api_port", "port", "WOW_API_PORT", 8000, int),
            "token": _get("api_token", "token", "WOW_API_TOKEN", ""),
        }

    @property
    def verbose(self) -> bool:
        """Whether debug logging is enabled (CLI flag > TOML root > env)."""
        if self.toml is None:
            raise TypeError("TOML not loaded yet")
        args = parse_args()
        return _resolve(args.verbose, self.toml.get("verbose"), # type: ignore
                        os.environ.get("WOW_VERBOSE"), False, _env_bool)
