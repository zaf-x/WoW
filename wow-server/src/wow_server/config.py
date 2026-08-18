"""Configuration: parse CLI flags / WOW_* environment variables into Server kwargs."""

import argparse
import importlib.util
import os
import uuid
from typing import Any, Callable

_args: argparse.Namespace | None = None


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments, falling back to WOW_* environment variables.

    The result is cached: repeated calls return the same namespace.

    Returns:
        The parsed arguments namespace.

    Raises:
        SystemExit: If a required argument is missing or the token is not
            a hex string (via ``parser.error``).
    """
    global _args
    if _args is not None:
        return _args
    parser = argparse.ArgumentParser(prog="wow-server", description="WoW VPN server")
    parser.add_argument("--host", default=os.environ.get("WOW_HOST", "0.0.0.0"),
                        help="listen address (default: 0.0.0.0, env WOW_HOST)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("WOW_PORT", "9999")),
                        help="listen port (default: 9999, env WOW_PORT)")
    parser.add_argument("--script-auth", action="store_true", default=bool(int(os.environ.get("WOW_SCRIPT_AUTH", "0"))),
                        help="Runs a python script for authentication")
    parser.add_argument("--auth-script", type=str, default=os.environ.get("WOW_AUTH_SCRIPT", ""),
                        help="The file used to authenticate")
    parser.add_argument("--idle-script", type=str, default=os.environ.get("WOW_IDLE_SCRIPT", ""),
                        help="Python file exporting idle_callback(), run after the server has "
                             "had no clients for --idle-timer seconds (env WOW_IDLE_SCRIPT)")
    parser.add_argument("--idle-timer", type=int, default=int(os.environ.get("WOW_IDLE_TIMER", "600")),
                        help="seconds without clients before idle_callback() fires "
                             "(default: 600, env WOW_IDLE_TIMER)")
    parser.add_argument("--token", default=os.environ.get("WOW_TOKEN"),
                        help="128-bit auth token as 32 hex chars (env WOW_TOKEN)")
    parser.add_argument("--iface", default=os.environ.get("WOW_IFACE"),
                        help="physical interface for NAT, e.g. ens5 (env WOW_IFACE)")
    parser.add_argument("--cert", default=os.environ.get("WOW_CERT"),
                        help="TLS certificate file (env WOW_CERT)")
    parser.add_argument("--key", default=os.environ.get("WOW_KEY"),
                        help="TLS private key file (env WOW_KEY)")
    parser.add_argument("--masquerade", action="store_true",
                        help="reply to bad auth with a fake success, then drop their traffic (camouflage)")
    parser.add_argument("--ipv6-prefix", default=os.environ.get("WOW_IPV6_PREFIX", "fd08::/64"),
                        help="IPv6 tunnel network, e.g. a provider-routed public /64 "
                             "(default: fd08::/64, env WOW_IPV6_PREFIX)")
    parser.add_argument("--ipv6-proxy-ndp", action="store_true",
                        default=bool(int(os.environ.get("WOW_IPV6_PROXY_NDP", "0"))),
                        help="proxy-NDP for client IPv6 addresses on the egress interface "
                             "(needed for on-link prefixes like AWS EC2, env WOW_IPV6_PROXY_NDP)")
    parser.add_argument("--ipv6-rotate-interval", type=int,
                        default=int(os.environ.get("WOW_IPV6_ROTATE_INTERVAL", "3600")),
                        help="seconds between reassigning each client a new random IPv6 "
                             "address (privacy rotation; 0 disables, default: 3600, env WOW_IPV6_ROTATE_INTERVAL)")
    parser.add_argument("--api-host", default=os.environ.get("WOW_API_HOST", "127.0.0.1"),
                        help="management API bind address (default: 127.0.0.1, env WOW_API_HOST)")
    parser.add_argument("--api-port", type=int, default=int(os.environ.get("WOW_API_PORT", "8000")),
                        help="management API port, 0 disables (default: 8000, env WOW_API_PORT)")
    parser.add_argument("--api-token", default=os.environ.get("WOW_API_TOKEN", ""),
                        help="bearer token for the management API; empty means no auth "
                             "(default: none, env WOW_API_TOKEN)")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    args = parser.parse_args()

    for name in ("token", "iface", "cert", "key"):
        if getattr(args, name) is None:
            parser.error(f"--{name} is required (or set WOW_{name.upper()})")
    try:
        args.token = int(args.token, 16)
    except ValueError:
        parser.error("--token must be a hex string")

    _args = args
    return args


def _load_function(path: str, attr: str) -> Callable[..., Any]:
    """Import a Python file and return the named callable from it.

    Args:
        path: Path to the Python script to import.
        attr: Name of the function the script must export.

    Returns:
        The exported callable.

    Raises:
        SystemExit: If the script cannot be imported or does not export
            ``attr``.
    """
    module_name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        print("E: invalid script: import failed")
        exit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return getattr(module, attr)
    except AttributeError:
        print(f"E: invalid script: must provide `{attr}` function")
        exit(1)


def _auth_handler(args: argparse.Namespace) -> Callable[[int], tuple[bool, int]]:
    """Build the auth handler from a script or the static token."""
    if args.script_auth:
        if not args.auth_script:
            print("Must give auth script when using script auth")
            exit(1)
        return _load_function(args.auth_script, "auth_handler")
    return lambda x: (args.token == x, uuid.uuid4().int)


def _idle_callback(args: argparse.Namespace) -> Callable[[], None] | None:
    """Load the idle callback from a script, or None if not configured."""
    if not args.idle_script:
        return None
    return _load_function(args.idle_script, "idle_callback")


def get_kwargs() -> dict[str, Any]:
    """Build the keyword arguments for :class:`wow_server.server.Server`.

    Parses CLI flags / ``WOW_*`` environment variables (via
    :func:`parse_args`) and loads the pluggable auth/idle scripts when
    configured.

    Returns:
        A dict suitable for ``Server(**get_kwargs())``.
    """
    args = parse_args()
    return {
        "host": args.host,
        "port": args.port,
        "interface": args.iface,
        "auth_handler": _auth_handler(args),
        "cert": args.cert,
        "key": args.key,
        "ipv6_prefix": args.ipv6_prefix,
        "proxy_ndp": args.ipv6_proxy_ndp,
        "ipv6_rotate_interval": args.ipv6_rotate_interval,
        "masquerade": args.masquerade,
        "idle_callback": _idle_callback(args),
        "idle_timer": args.idle_timer,
    }
