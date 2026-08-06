"""Command-line entry point for the WoW VPN client."""

import argparse
import asyncio
import ssl
from .client import Client

async def main():
    """Parse arguments, then run the client until interrupted, always stopping cleanly."""
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--host", type=str, required=True, help="Server host")
    parser.add_argument("-p", "--port", type=int, required=True, help="Server port")
    parser.add_argument("-t", "--token", type=str, required=True, help="Authenticate token")
    parser.add_argument("-c", "--ca-cert", type=str, default=None,
                        help="Path to a PEM CA certificate to trust for verifying the server "
                             "(default: system CA bundle)")
    args = parser.parse_args()
    client = Client(
        args.host,
        args.port,
        args.token,
        ca_cert=args.ca_cert,
    )

    try:
        await client.run()
    except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError, OSError) as exc:
        # Server dropped the connection or the TLS handshake failed; report it
        # without a traceback. KeyboardInterrupt is handled outside asyncio.run.
        print(f"Connection failed: {exc}")
    finally:
        await client.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
