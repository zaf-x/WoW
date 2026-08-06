"""WoW VPN client: connects to the server, sets up the TUN device and forwards traffic."""

import asyncio
import ssl
from wow_common.protocol import ApplicationData, Authentication, AuthenticationResponse, Ping, unpack  # type: ignore
from wow_common.tun import Tun # type: ignore
import socket
import ipaddress
import rich
from rich.panel import Panel
from rich.live import Live
from rich.table import Table

def human_size(size: float) -> str:
    """Format a byte count as a human-readable string.

    Args:
        size: Number of bytes.

    Returns:
        A string like ``"1.50 MB"``.
    """
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if abs(size) < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} EB"

class Client:
    """WoW VPN client.

    Establishes a TLS connection to the server, authenticates with a
    128-bit token, configures a local TUN device with the assigned tunnel
    address, and shuttles IP packets between the TUN device and the tunnel
    while showing a live status panel in the terminal.

    Attributes:
        server_host: VPN server hostname or address.
        server_port: VPN server port.
        fwmark: Netfilter mark applied to the tunnel's own outer socket so
            its traffic bypasses the TUN routing rules.
        running: Whether the client main loop is still active.
    """

    def __init__(self, server_host: str, server_port: int, token: str, ca_cert: str | None = None, fwmark: int = 0x1):
        """Initialize the client.

        Args:
            server_host: VPN server hostname or address.
            server_port: VPN server port.
            token: 128-bit authentication token as a hex string.
            ca_cert: Path to a PEM CA certificate file to trust for
                verifying the server. If None, the system default CA
                bundle is used.
            fwmark: Netfilter mark for the outer socket (must match the
                value passed to :meth:`Tun.setup_routing`).
        """
        self.server_host = server_host
        self.server_port = server_port
        self.ca_cert = ca_cert
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.token: int = int(token, 16)
        self.fwmark = fwmark
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, self.fwmark)
        self.sock.setblocking(False)
        self.ip = ""
        self.cidr = 0
        self.tun: Tun | None = None
        self.running: bool = True

        self.uplink_d: int = 0
        self.downlink_d: int = 0

        self.pending: asyncio.Queue[bytes] = asyncio.Queue()
        # Instantiate a rich Console object for rendering.
        self.console = rich.console.Console()
        # Placeholder for the live status panel, created in run().
        self.live: Live | None = None

    def _generate_panel(self, status_text: str, status_style: str = "cyan") -> Panel:
        """Build a live status Panel from the current data and state.

        Args:
            status_text: Human-readable connection status to display.
            status_style: Rich style applied to the status text.

        Returns:
            The rendered :class:`rich.panel.Panel` object.
        """
        table = Table.grid(padding=(0, 2))
        table.add_column("Property", style="bold cyan")
        table.add_column("Value")

        # Core system information.
        table.add_row("Server Host:", f"[yellow]{self.server_host}:{self.server_port}[/yellow]")
        table.add_row("TUN Status:", f"[{status_style}]{status_text}[/{status_style}]")

        # Show network details only once the TUN device has an assigned IP.
        if self.tun and hasattr(self, 'ip_addr'):
            table.add_row("Assigned IP:", f"[green]{self.ip_addr}/{self.cidr}[/green]")
        else:
            table.add_row("Assigned IP:", "[dim]Not Assigned[/dim]")

        # Live traffic counters.
        table.add_row("Uplink Data:", f"[bold green]{human_size(self.uplink_d)}[/bold green]")
        table.add_row("Downlink Data:", f"[bold blue]{human_size(self.downlink_d)}[/bold blue]")

        return Panel(
            table,
            title="[bold green]🔒 WOW VPN Client Status[/bold green]",
            border_style="green" if self.tun else "yellow",
            expand=False
        )

    def update_panel(self, status_text: str, status_style: str = "cyan"):
        """Safely update the panel contents while the Live display is running.

        Args:
            status_text: Human-readable connection status to display.
            status_style: Rich style applied to the status text.
        """
        if self.live:
            self.live.update(self._generate_panel(status_text, status_style))

    async def run(self):
        """Connect to the server and run the main forwarding loop.

        Connects over TLS, authenticates, configures the TUN device and
        policy routing, then forwards packets until :meth:`stop` is called.

        Raises:
            ValueError: If the server speaks an unexpected protocol or the
                token is rejected.
        """
        ssl_context = ssl.create_default_context(cafile=self.ca_cert)
        loop = asyncio.get_running_loop()

        # Start the persistent Live rendering context for the terminal.
        with Live(self._generate_panel("Connecting...", "yellow"), console=self.console, refresh_per_second=4) as live:
            self.live = live

            await loop.sock_connect(self.sock, (self.server_host, self.server_port))
            self.update_panel("Authenticating...", "yellow")

            self.reader, self.writer = await asyncio.open_connection(sock=self.sock, ssl=ssl_context, server_hostname=self.server_host)

            auth = Authentication(self.token)
            self.writer.write(auth.pack())
            await self.writer.drain()

            auth_resp = await self.read_packet()
            if not isinstance(auth_resp, AuthenticationResponse):
                raise ValueError("Invalid server protocol")

            if not auth_resp.success:
                raise ValueError("Invalid token")

            ip = auth_resp.ip_addr
            self.cidr = auth_resp.ip_cidr

            self.ip_addr = ipaddress.IPv4Address(ip)
            self.tun = Tun("wowtun")
            self.tun.up()
            self.tun.set_addr(f"{self.ip_addr}/{self.cidr}")
            self.tun.setup_routing(self.fwmark, bypass_ip=socket.gethostbyname(self.server_host))
            self.tun.setup_dns()

            # TUN setup is complete; switch the status to Running.
            print("\033c")
            self.update_panel("Running", "green")

            loop.add_reader(self.tun.fileno(), self.manage_new_data)
            asyncio.create_task(self.send_data_loop())
            asyncio.create_task(self.ping_loop())

            while self.running:
                pkt = await self.read_packet()
                if isinstance(pkt, ApplicationData):
                    self.tun.write(pkt.data)
                    self.downlink_d += len(pkt.data)
                    # Downlink data received; refresh the panel with the latest counters.
                    self.update_panel("Running", "green")
                await self.writer.drain()

            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
            self.reader = None

    async def ping_loop(self):
        """Send a Ping every 5 seconds to keep the tunnel alive."""
        while self.running:
            if not self.writer:
                break
            self.writer.write(Ping().pack())
            await self.writer.drain()
            # Refresh the panel on heartbeats too, so the UI does not look frozen when there is no traffic.
            self.update_panel("Running (Ping Sent)", "green")
            await asyncio.sleep(5)

    async def stop(self):
        """Tear down routing, DNS and the TUN device, and stop the main loop."""
        if not self.tun:
            return

        # Show the shutting-down state in the live panel first.
        self.update_panel("Stopping...", "red")
        await asyncio.sleep(0.5)  # Give the live display a brief moment to refresh.

        self.running = False
        self.tun.teardown_routing()
        self.tun.teardown_dns()
        self.tun.close()
        loop = asyncio.get_running_loop()
        loop.remove_reader(self.tun.fileno())

        # Print the final message after the Live context has exited.
        self.console.print("[bold red]Disconnected and Stopped[/bold red]")

    async def read_packet(self):
        """Read a single framed packet from the tunnel.

        Returns:
            The decoded packet object.

        Raises:
            ValueError: If the client is not connected yet.
        """
        if not self.reader:
            raise ValueError("not connected yet")
        length = await self.reader.readexactly(4)
        data = await self.reader.readexactly(int.from_bytes(length, "big"))
        return unpack(length + data)

    def manage_new_data(self):
        """Event-loop callback: read a packet from the TUN device and queue it for sending."""
        if not self.tun or not self.writer:
            return
        data = self.tun.read()
        self.pending.put_nowait(data)

    async def send_data_loop(self):
        """Forward queued TUN packets to the server as ApplicationData frames."""
        while self.running:
            data = await self.pending.get()
            if not self.writer:
                break

            self.writer.write(ApplicationData(data).pack())
            self.uplink_d += len(data)
            # Uplink data sent; refresh the panel with the latest counters.
            self.update_panel("Running", "green")
            await self.writer.drain()
