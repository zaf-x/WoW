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
        susp: Whether this remote is marked as suspicious (masquerade).
        reader: Stream reader for the TLS connection.
        writer: Stream writer for the TLS connection.
        client_v4: Assigned tunnel IPv4 address as an integer, if any.
        client_v6: Assigned tunnel IPv6 address as an integer, if any.
    """

    stream_id: str
    authorized: bool
    susp: bool

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    client_v4: int | None = None
    client_v6: int | None = None

class Server:
    """WoW VPN server.

    Listens for TLS connections, authenticates clients with a shared
    128-bit token, and shuttles IP packets between a single gateway TUN
    device (``wowgateway``) and the clients' tunnels. The gateway acts as
    a router: its egress is the physical interface (with NAT), and reply
    packets are demultiplexed to the owning client by destination address.

    Attributes:
        host: Listen address.
        port: Listen port.
        auth_handler: The handler of authentication, accepts a 128-bit authentication token as an integer.
        interface: Physical egress interface used for NAT.
        masquerade: If True, answer bad authentication attempts with a
            fake success and silently drop the connection's traffic
            (camouflage).
        ipv6_net: The IPv6 tunnel network clients are assigned from.
        tun: The shared gateway TUN device, created in :meth:`serve`.
        addr_map: Maps ``(family, address)`` to the client owning that address.
    """

    def __init__(self, host: str, port: int, auth_handler: Callable[[int], bool], interface: str, cert: str, key: str, masquerade: bool = False, ipv6_prefix: str = "fd08::/64", proxy_ndp: bool = False):
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
            proxy_ndp: Proxy-NDP for client addresses on the physical
                interface. Needed for on-link IPv6 prefixes such as AWS
                EC2, where the instance owns a single /128 of the subnet.
        """
        self.host = host
        self.port = port
        self.cert = cert
        self.key = key
        self.auth_handler = auth_handler
        self.masquerade = masquerade
        self.interface = interface
        self.ip_cnt = 1
        self.proxy_ndp = proxy_ndp
        self.ipv6_net = ipaddress.IPv6Network(ipv6_prefix, strict=False)

        self.running = True
        self.remotes: list[Remote] = []
        self.tun: Tun | None = None
        self.addr_map: dict[tuple[int, int], Remote] = {}

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
        remote = Remote(uuid.uuid4().hex, False, False, reader, writer)
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
        if remote.client_v4 is not None:
            self.addr_map.pop((4, remote.client_v4), None)
        if remote.client_v6 is not None:
            self.addr_map.pop((6, remote.client_v6), None)
            if self.proxy_ndp and self.tun is not None:
                self.tun.teardown_proxy_ndp(str(ipaddress.IPv6Address(remote.client_v6)))
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
            self.ip_cnt += 1
            # Flat tunnel networks behind the gateway TUN: IPv4 10.8.0.0/24
            # (server 10.8.0.1, clients 10.8.0.N); IPv6 prefix configurable
            # (default ULA fd08::/64, or a public prefix for global addresses).
            client_ip = 0xA080000 | self.ip_cnt
            client_v6 = int(self.ipv6_net.network_address) | self.ip_cnt
            self.addr_map[(4, client_ip)] = remote
            self.addr_map[(6, client_v6)] = remote
            if self.proxy_ndp and self.ipv6_net.is_global and self.tun is not None:
                # On-link prefixes (AWS EC2): answer NDP for the client's
                # global address on the physical interface.
                self.tun.setup_proxy_ndp(self.interface, str(ipaddress.IPv6Address(client_v6)))
            remote.client_v4 = client_ip
            remote.client_v6 = client_v6

            return [
                AuthenticationResponse(True),
                IPv4Assign(client_ip, 24),
                IPv6Assign(client_v6, self.ipv6_net.prefixlen),
            ]
        if isinstance(packet, ApplicationData):
            if not self.tun:
                return []

            self.tun.write(packet.data)
        if isinstance(packet, Ping):
            return [Pong()]

        print(f"Susp remote: {remote}")
        remote.susp = True
        return []

    async def serve(self) -> None:
        """Create the gateway TUN, then start the TLS listener and serve clients forever."""
        # One shared gateway TUN acting as the router for all clients. It
        # holds the tunnel networks, NATs on egress and demultiplexes
        # replies to the owning client by destination address.
        tun = Tun("wowgateway")
        tun.up()
        tun.set_addr("10.8.0.1/24")
        tun.set_addr(f"{self.ipv6_net.network_address + 1}/{self.ipv6_net.prefixlen}")
        tun.setup_nat(self.interface, ipv6_masquerade=not self.ipv6_net.is_global)
        self.tun = tun
        asyncio.get_running_loop().add_reader(tun.fileno(), self.on_gateway_readable)

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
        """Stop the server, tear down all connected clients and the gateway TUN."""
        self.running = False
        while self.remotes:
            remote = self.remotes.pop()
            await self.teardown_remote(remote)
        if self.tun is not None:
            loop = asyncio.get_running_loop()
            loop.remove_reader(self.tun.fileno())
            self.tun.teardown_nat()
            self.tun.close()
            self.tun = None

    def on_gateway_readable(self):
        """Event-loop callback: read a packet from the gateway TUN and send it to the owning client.

        The packet is routed to whichever client was assigned its
        destination address.
        """
        if self.tun is None:
            return
        data = self.tun.read()
        if len(data) < 20:
            return
        version = data[0] >> 4
        if version == 4:
            key = (4, int.from_bytes(data[16:20], "big"))
        elif version == 6 and len(data) >= 40:
            key = (6, int.from_bytes(data[24:40], "big"))
        else:
            return
        remote = self.addr_map.get(key)
        if remote is None or remote.writer.is_closing():
            return
        remote.writer.write(ApplicationData(data).pack())
