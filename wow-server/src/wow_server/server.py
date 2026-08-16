"""WoW VPN server: accepts TLS clients, authenticates them and forwards tunnelled traffic."""

from dataclasses import dataclass
import ipaddress
import asyncio
import ssl
from typing import Callable
from wow_common.protocol import Raw, unpack, PacketType, Authentication, AuthenticationResponse, IPv4Assign, IPv6Assign, ApplicationData, Ping, Pong  # type: ignore
from wow_common.tun import Tun # type: ignore
import uuid
import rich

@dataclass
class Remote:
    """Per-connection state for a connected client.

    Attributes:
        stream_id: Random hex identifier for the connection.
        authorized: Whether the client has successfully authenticated.
        tun: The TUN device created for this client, if any.
        susp: Is this remote marked as some kind of auto inspector
        reader: Stream reader for the TLS connection.
        writer: Stream writer for the TLS connection.
    """

    stream_id: str
    authorized: bool
    tun: Tun | None
    susp: bool

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

class Server:
    """WoW VPN server.

    Listens for TLS connections, authenticates clients with a shared
    128-bit token, creates a per-client TUN device with NAT, and shuttles
    IP packets between each client's TUN device and its tunnel.

    Attributes:
        host: Listen address.
        port: Listen port.
        auth_handler: The handler of authentication, accepts a 128-bit authentication token as an integer.
        interface: Physical egress interface used for NAT.
        masquerade: If True, silently drop bad authentication attempts
            instead of replying with a failure (camouflage).
        ipv6_net: The IPv6 tunnel network clients are assigned from.
    """

    def __init__(self, host: str, port: int, auth_handler: Callable[[int], bool], interface: str, cert: str, key: str, masquerade: bool = False, ipv6_prefix: str = "fd08::/64"):
        """Initialize the server.

        Args:
            host: Listen address.
            port: Listen port.
            token: The shared 128-bit authentication token as an integer.
            interface: Physical egress interface used for NAT, e.g. ``"ens5"``.
            cert: Path to the TLS certificate file.
            key: Path to the TLS private key file.
            masquerade: Silently drop bad auth instead of replying.
            ipv6_prefix: IPv6 tunnel network in CIDR form. Defaults to the
                ULA ``fd08::/64``; use a global prefix (e.g. a provider
                routed ``/64``) to hand clients public IPv6 addresses.
        """
        self.host = host
        self.port = port
        self.cert = cert
        self.key = key
        self.auth_handler = auth_handler
        self.masquerade = masquerade
        self.interface = interface
        self.ip_cnt = 2
        self.ipv6_net = ipaddress.IPv6Network(ipv6_prefix, strict=False)

        self.running = True
        self.remotes: list[Remote] = []

    async def handle_stream(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve one client connection: read, dispatch and reply to packets until disconnect.

        Args:
            reader: Stream reader for the accepted TLS connection.
            writer: Stream writer for the accepted TLS connection.
        """
        peer_addr = writer.get_extra_info("peername")
        rich.print(f"[green]New connection from {peer_addr}[/green]")
        remote = Remote(uuid.uuid4().hex, False, None, False, reader, writer)
        self.remotes.append(remote)

        try:
            while self.running:
                # Read the 4-byte length header exactly.
                length_bytes = await reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")

                # Read the payload exactly.
                data = await reader.readexactly(length)

                packet = unpack(length_bytes + data)

                responses = await self.manage_packet(remote, packet)
                for resp in responses:
                    writer.write(resp.pack())
                await writer.drain()

        except asyncio.IncompleteReadError:
            rich.print(f"Client {peer_addr} disconnected")
        except Exception:
            rich.print(f"[red]E: Unhandled exception from {peer_addr}[/red]")
        finally:
            await self.teardown_remote(remote)

    async def teardown_remote(self, remote: Remote):
        """Release all resources held by a client connection.

        Args:
            remote: The connection to tear down.
        """
        if remote.tun is not None:
            asyncio.get_running_loop().remove_reader(remote.tun.fileno())
            remote.tun.teardown_nat()
            remote.tun.close()
            remote.tun = None
        remote.writer.close()
        await remote.writer.wait_closed()

    async def manage_packet(self, remote: Remote, packet: PacketType) -> list[PacketType]:
        """Handle one decoded packet from a client.

        Args:
            remote: The connection the packet arrived on.
            packet: The decoded packet.

        Returns:
            A list of response packets to send back (possibly empty).
        """
        if remote.susp and self.masquerade:
            return []
        if isinstance(packet, Authentication):
            if not self.auth_handler(packet.token):
                if not self.masquerade:
                    return [AuthenticationResponse(False)]
                remote.susp = True
                print(f"Susp remote: {remote}")
            remote.authorized = True
            remote.tun = Tun(f"wowtun{remote.stream_id[:9]}")
            remote.tun.up()
            remote.tun.setup_nat(self.interface, ipv6_masquerade=not self.ipv6_net.is_global)
            loop = asyncio.get_running_loop()
            loop.add_reader(remote.tun.fileno(), lambda: self.on_tun_readable(remote))
            self.ip_cnt += 1
            # Tunnel networks: IPv4 10.8.0.0/24; IPv6 prefix configurable
            # (default ULA fd08::/64, or a public prefix for global addresses).
            client_ip = 0xA080000 | self.ip_cnt
            client_addr = str(ipaddress.IPv4Address(client_ip))
            remote.tun.add_route(f"{client_addr}/32")
            remote.tun.set_addr("10.8.0.1/24")
            client_v6 = int(self.ipv6_net.network_address) | self.ip_cnt
            client_v6_addr = str(ipaddress.IPv6Address(client_v6))
            # A /128 route pins replies to this client to its own TUN even
            # though every per-client TUN shares the tunnel /64.
            remote.tun.add_route(f"{client_v6_addr}/128")
            remote.tun.set_addr(f"{self.ipv6_net.network_address + 1}/{self.ipv6_net.prefixlen}")

            return [
                AuthenticationResponse(True),
                IPv4Assign(client_ip, 24),
                IPv6Assign(client_v6, self.ipv6_net.prefixlen),
            ]
        if isinstance(packet, ApplicationData):
            if not remote.tun:
                return []

            remote.tun.write(packet.data)
        if isinstance(packet, Ping):
            return [Pong()]

        print(f"Susp remote: {remote}")
        remote.susp = True
        return []

    async def serve(self) -> None:
        """Start the TLS listener and serve clients forever."""
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(self.cert, self.key)

        server = await asyncio.start_server(
            self.handle_stream,
            self.host,
            self.port,
            ssl=ssl_ctx,
        )
        rich.print(f"[green]Server listening on {self.host}:{self.port}[/green]")

        async with server:
            await server.serve_forever()

    async def stop(self):
        """Stop the server and tear down all connected clients."""
        self.running = False
        while self.remotes:
            remote = self.remotes.pop()
            await self.teardown_remote(remote)

    def on_tun_readable(self, remote: Remote):
        """Event-loop callback: read a reply packet from the client's TUN and send it down the tunnel.

        Args:
            remote: The connection whose TUN device became readable.
        """
        if remote.tun is None or remote.writer.is_closing():
            return
        data = remote.tun.read()
        packet = ApplicationData(data)
        remote.writer.write(packet.pack())
