"""Command-line entry point for the WoW VPN server."""

import argparse
import asyncio
import contextlib
import logging
import os
import importlib.util
from collections.abc import Generator
from typing import Callable
import uuid

import uvicorn

from .server import Server
from .api import API


class _EmbeddedServer(uvicorn.Server):
    """uvicorn server that never installs its own signal handlers.

    uvicorn >= 0.30 removed the ``install_signal_handlers`` constructor flag:
    ``serve()`` now unconditionally replaces the SIGINT/SIGTERM handlers on the
    main thread via ``capture_signals()``. When embedded on the VPN server's own
    loop that would swallow Ctrl+C (and systemd's SIGTERM), so override it with a
    no-op; graceful shutdown still works because ``main()`` sets ``should_exit``.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        yield


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments, falling back to WOW_* environment variables.

    Returns:
        The parsed arguments namespace.

    Raises:
        SystemExit: If a required argument is missing or the token is not
            a hex string (via ``parser.error``).
    """
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

    return args


def main() -> None:
    """Run the server until interrupted."""
    args = parse_args()
    auth_handler: Callable[[int], tuple[bool, int]] | None = None
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    if args.script_auth:
        if not args.auth_script:
            print("Must give auth script when using script auth")
            exit(1)

        module_name = os.path.splitext(os.path.basename(args.auth_script))[0]
        spec = importlib.util.spec_from_file_location(module_name, args.auth_script)
        if spec is None or spec.loader is None:
            print("E: invalid script: import failed")
            exit(1)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        try:
            auth_handler = module.auth_handler
        except AttributeError:
            print("E: invalid script: must provide `auth_handler` function")
            exit(1)
    else:
        auth_handler = (lambda x: (args.token == x, uuid.uuid4().int))

    if not auth_handler:
        auth_handler = lambda x: (False, 0) # Satisfy PyLance

    idle_callback: Callable[[], None] | None = None
    if args.idle_script:
        module_name = os.path.splitext(os.path.basename(args.idle_script))[0]
        spec = importlib.util.spec_from_file_location(module_name, args.idle_script)
        if spec is None or spec.loader is None:
            print("E: invalid script: import failed")
            exit(1)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            idle_callback = module.idle_callback
        except AttributeError:
            print("E: invalid script: must provide `idle_callback` function")
            exit(1)

    server = Server(args.host, args.port, args.iface, auth_handler,
                    args.cert, args.key, masquerade=args.masquerade,
                    ipv6_prefix=args.ipv6_prefix, proxy_ndp=args.ipv6_proxy_ndp,
                    idle_callback=idle_callback, idle_timer=args.idle_timer,
                    ipv6_rotate_interval=args.ipv6_rotate_interval)

    async def run() -> None:
        """Run the VPN server and, when enabled, the management API on the same loop."""
        api_task = None
        uvicorn_server = None
        if args.api_port:
            api = API(server, token=args.api_token)
            config = uvicorn.Config(
                api.app, host=args.api_host, port=args.api_port, log_level="warning"
            )
            uvicorn_server = _EmbeddedServer(config)
            api_task = asyncio.create_task(uvicorn_server.serve())

        try:
            await server.serve()
        finally:
            if uvicorn_server is not None:
                uvicorn_server.should_exit = True
            if api_task is not None:
                await asyncio.gather(api_task, return_exceptions=True)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
