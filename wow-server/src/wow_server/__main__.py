import argparse
import asyncio
import logging
import os

from .server import Server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="wow-server", description="WoW VPN server")
    parser.add_argument("--host", default=os.environ.get("WOW_HOST", "0.0.0.0"),
                        help="listen address (default: 0.0.0.0, env WOW_HOST)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("WOW_PORT", "9999")),
                        help="listen port (default: 9999, env WOW_PORT)")
    parser.add_argument("--token", default=os.environ.get("WOW_TOKEN"),
                        help="128-bit auth token as 32 hex chars (env WOW_TOKEN)")
    parser.add_argument("--iface", default=os.environ.get("WOW_IFACE"),
                        help="physical interface for NAT, e.g. ens5 (env WOW_IFACE)")
    parser.add_argument("--cert", default=os.environ.get("WOW_CERT"),
                        help="TLS certificate file (env WOW_CERT)")
    parser.add_argument("--key", default=os.environ.get("WOW_KEY"),
                        help="TLS private key file (env WOW_KEY)")
    parser.add_argument("--masquerade", action="store_true",
                        help="silently drop bad auth instead of replying (camouflage)")
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
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    server = Server(args.host, args.port, args.token, args.iface,
                    args.cert, args.key, masquerade=args.masquerade)
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
