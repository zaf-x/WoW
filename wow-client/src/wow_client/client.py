"""WoW VPN client: connects to the server, sets up the TUN device and forwards traffic."""

import asyncio
from collections import deque
import ssl
from wow_common.protocol import ApplicationData, Authentication, AuthenticationResponse, Ping, Pong, unpack  # type: ignore
from wow_common.tun import Tun # type: ignore
import socket
import time
import os
import struct
import ipaddress
import rich
from rich.panel import Panel
from rich.live import Live
from rich.table import Table

# Public host pinged over ICMP to measure the client-to-internet delay through the tunnel.
INTERNET_PROBE_HOST = "1.1.1.1"

# Rolling window (seconds) over which the uplink/downlink transfer rates are averaged.
RATE_WINDOW_SECONDS = 5.0

# Minimum interval between transfer-rate samples, so that bursts of packets do not
# flood the rolling history with near-identical snapshots.
RATE_SAMPLE_INTERVAL = 0.25

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

def format_delay(delay: float | None) -> str:
    """Format a delay in seconds as a millisecond string.

    Args:
        delay: Delay in seconds, or None if it has not been measured yet.

    Returns:
        A string like ``"12.3 ms"``, or ``"N/A"`` when unmeasured.
    """
    if delay is None:
        return "N/A"
    return f"{delay * 1000:.1f} ms"

def transfer_rate(samples: deque[tuple[float, int]], total: int) -> float:
    """Compute the average transfer rate over the recent rolling window.

    Appends a fresh ``(now, total)`` snapshot (throttled to
    ``RATE_SAMPLE_INTERVAL``) and averages the byte delta over the
    snapshots retained within ``RATE_WINDOW_SECONDS``.

    Args:
        samples: Deque of recent ``(timestamp, cumulative bytes)``
            snapshots for one direction. Mutated in place.
        total: Current cumulative byte count for that direction.

    Returns:
        Bytes per second averaged over the window, or ``0.0`` when there
        is not enough data yet.
    """
    now = time.monotonic()
    if not samples or now - samples[-1][0] >= RATE_SAMPLE_INTERVAL:
        samples.append((now, total))
    else:
        # Refresh the newest snapshot's total so a just-finished burst keeps
        # counting while the window slides.
        samples[-1] = (samples[-1][0], total)
    while samples and now - samples[0][0] > RATE_WINDOW_SECONDS:
        samples.popleft()
    if len(samples) < 2:
        return 0.0
    elapsed = now - samples[0][0]
    if elapsed <= 0:
        return 0.0
    return (total - samples[0][1]) / elapsed

def _icmp_checksum(data: bytes) -> int:
    """Compute the standard internet checksum over ``data``."""
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF

def build_icmp_echo(identifier: int, sequence: int) -> bytes:
    """Build an ICMP echo-request packet with the given id and sequence number."""
    payload = b"wow-vpn-probe"
    header = struct.pack("!BBHHH", 8, 0, 0, identifier, sequence)
    header = struct.pack("!BBHHH", 8, 0, _icmp_checksum(header + payload), identifier, sequence)
    return header + payload

def is_echo_reply(data: bytes, identifier: int, sequence: int) -> bool:
    """Return True if ``data`` is the ICMP echo reply matching our probe.

    Args:
        data: A full IPv4 packet as received on a raw ICMP socket.
        identifier: The ICMP id our probe used.
        sequence: The ICMP sequence number our probe used.
    """
    if len(data) < 20:
        return False
    ihl = (data[0] & 0x0F) * 4
    icmp = data[ihl:]
    if len(icmp) < 8:
        return False
    pkt_type, code, _, reply_id, reply_seq = struct.unpack("!BBHHH", icmp[:8])
    return pkt_type == 0 and code == 0 and reply_id == identifier and reply_seq == sequence

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

        # Rolling (timestamp, cumulative bytes) snapshots used to compute transfer rates.
        self._uplink_samples: deque[tuple[float, int]] = deque()
        self._downlink_samples: deque[tuple[float, int]] = deque()

        self.server_delay: float | None = None
        self.internet_delay: float | None = None
        self.last_ping_at: float | None = None

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

        # Live traffic: transfer rate as the headline value, with the cumulative total in brackets.
        table.add_row("Uplink Data:", f"[bold green]{human_size(transfer_rate(self._uplink_samples, self.uplink_d))}/s[/bold green] ([dim]{human_size(self.uplink_d)}[/dim])")
        table.add_row("Downlink Data:", f"[bold blue]{human_size(transfer_rate(self._downlink_samples, self.downlink_d))}/s[/bold blue] ([dim]{human_size(self.downlink_d)}[/dim])")

        # Latency measurements, "N/A" until the first round completes.
        table.add_row("Client to Server Delay:", f"[yellow]{format_delay(self.server_delay)}[/yellow]")
        table.add_row("Client to Internet Delay:", f"[yellow]{format_delay(self.internet_delay)}[/yellow]")

        return Panel(
            table,
            title="[bold green]🔒 WoW VPN Client Status[/bold green]",
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
            asyncio.create_task(self.internet_delay_loop())

            while self.running:
                pkt = await self.read_packet()
                if isinstance(pkt, ApplicationData):
                    self.tun.write(pkt.data)
                    self.downlink_d += len(pkt.data)
                    # Downlink data received; refresh the panel with the latest counters.
                    self.update_panel("Running", "green")
                elif isinstance(pkt, Pong):
                    if self.last_ping_at is not None:
                        self.server_delay = time.monotonic() - self.last_ping_at
                        self.update_panel("Running", "green")
                await self.writer.drain()

            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
            self.reader = None

    async def ping_loop(self):
        """Send a Ping every 5 seconds to keep the tunnel alive.

        Records the send time so the Pong handler in the main loop can
        compute the client-to-server delay.
        """
        while self.running:
            if not self.writer:
                break
            self.last_ping_at = time.monotonic()
            self.writer.write(Ping().pack())
            await self.writer.drain()
            # Refresh the panel on heartbeats too, so the UI does not look frozen when there is no traffic.
            self.update_panel("Running (Ping Sent)", "green")
            await asyncio.sleep(5)

    async def internet_delay_loop(self):
        """Measure the client-to-internet delay through the tunnel every 5 seconds.

        Sends an ICMP echo request (ping) to a public host via a raw socket;
        the socket carries no fwmark, so the probe is routed through the TUN
        like ordinary traffic.
        """
        identifier = os.getpid() & 0xFFFF
        sequence = 0
        while self.running:
            sequence = (sequence + 1) & 0xFFFF
            self.internet_delay = await self._icmp_ping(identifier, sequence)
            if self.running:
                self.update_panel("Running", "green")
            await asyncio.sleep(5)

    async def _icmp_ping(self, identifier: int, sequence: int) -> float | None:
        """Send one ICMP echo request to the probe host and time the reply.

        Uses a raw socket, which requires root — the client already runs as
        root for the TUN device.

        Returns:
            The round-trip time in seconds, or None on timeout or error.
        """
        loop = asyncio.get_running_loop()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
            sock.setblocking(False)
        except OSError:
            return None
        try:
            await loop.sock_sendto(sock, build_icmp_echo(identifier, sequence), (INTERNET_PROBE_HOST, 0))
            start = time.monotonic()
            deadline = start + 5
            while True:
                # Keep consuming until the reply matching our id/sequence arrives.
                data, _ = await asyncio.wait_for(loop.sock_recvfrom(sock, 1024), timeout=deadline - time.monotonic())
                if is_echo_reply(data, identifier, sequence):
                    return time.monotonic() - start
        except (OSError, asyncio.TimeoutError):
            return None
        finally:
            sock.close()

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
