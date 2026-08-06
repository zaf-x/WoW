"""Command-line entry point for the WoW VPN client."""

import argparse
import asyncio
import ssl

from rich.console import Console
from rich.prompt import IntPrompt
from rich.table import Table

from .client import Client
from .config import CONFIG_PATH, Profile, load_profiles, save_profile

SAMPLE_CONFIG = """{
  "profiles": {
    "my-server": {
      "host": "vpn.example.com",
      "port": 443,
      "token": "<128-bit token as hex>",
      "ca_cert": null
    }
  }
}"""


async def run_client(client: Client):
    """Run the client until interrupted, always stopping cleanly."""
    try:
        await client.run()
    except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError, OSError) as exc:
        # Server dropped the connection or the TLS handshake failed; report it
        # without a traceback. KeyboardInterrupt is handled outside asyncio.run.
        print(f"Connection failed: {exc}")
    finally:
        await client.stop()


def pick_profile(console: Console) -> Profile:
    """Interactively pick one of the saved profiles.

    Lists the profiles from the config file in a table and asks the user
    to choose one by number.

    Args:
        console: Rich console used for the wizard output.

    Returns:
        The chosen :class:`Profile`.

    Raises:
        SystemExit: If the config file is invalid or no profiles are saved.
    """
    try:
        profiles = load_profiles()
    except ValueError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise SystemExit(1)

    if not profiles:
        console.print(f"[bold red]No saved profiles found in {CONFIG_PATH}[/bold red]")
        console.print(f"Create it with a profile like:\n{SAMPLE_CONFIG}")
        raise SystemExit(1)

    table = Table(title="Saved Profiles")
    table.add_column("#", style="bold cyan", justify="right")
    table.add_column("Name", style="bold green")
    table.add_column("Server", style="yellow")
    table.add_column("Token")
    names = list(profiles)
    for i, name in enumerate(names, 1):
        profile = profiles[name]
        # Never display the full token.
        masked = profile.token[:4] + "..." if len(profile.token) > 4 else "..."
        table.add_row(str(i), name, f"{profile.host}:{profile.port}", masked)
    console.print(table)

    choice = IntPrompt.ask(
        "Select a profile",
        choices=[str(i) for i in range(1, len(names) + 1)],
        console=console,
    )
    return profiles[names[choice - 1]]


async def main():
    """Parse arguments, then run the client until interrupted, always stopping cleanly."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Server connection arguments shared by the start and save subcommands.
    server_args = argparse.ArgumentParser(add_help=False)
    server_args.add_argument("-s", "--host", type=str, required=True, help="Server host")
    server_args.add_argument("-p", "--port", type=int, required=True, help="Server port")
    server_args.add_argument("-t", "--token", type=str, required=True, help="Authenticate token")
    server_args.add_argument("-c", "--ca-cert", type=str, default=None,
                             help="Path to a PEM CA certificate to trust for verifying the server "
                                  "(default: system CA bundle)")

    subparsers.add_parser("start", parents=[server_args],
                          help="Connect to a server given on the command line")

    save_parser = subparsers.add_parser("save", parents=[server_args],
                                        help="Save a server configuration as a named profile")
    save_parser.add_argument("name", type=str, help="Profile name")

    subparsers.add_parser("launch", help="Pick a saved profile and connect")

    args = parser.parse_args()

    if args.command == "save":
        console = Console()
        try:
            save_profile(args.name, Profile(args.host, args.port, args.token, ca_cert=args.ca_cert))
        except ValueError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            raise SystemExit(1)
        console.print(f"Profile [bold green]{args.name}[/bold green] saved to {CONFIG_PATH}")
        return

    if args.command == "start":
        client = Client(args.host, args.port, args.token, ca_cert=args.ca_cert)
    else:  # launch
        profile = pick_profile(Console())
        client = Client(profile.host, profile.port, profile.token, ca_cert=profile.ca_cert)

    await run_client(client)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
