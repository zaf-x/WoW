"""WoW VPN server: accepts TLS clients, authenticates them and forwards tunnelled traffic."""

from dataclasses import dataclass
import ipaddress
import asyncio
import random
import socket
import ssl
from typing import Callable
from wow_common.protocol import unpack, PacketType, Authentication, AuthenticationResponse, IPv4Assign, IPv6Assign, ApplicationData, Ping, Pong  # type: ignore
from wow_common.tun import Tun # type: ignore
import rich

@dataclass
class Remote:
    """Per-connection state for a connected client.

    Attributes:
        remote_id: Stable id for the connection, assigned by
            ``auth_handler`` at authentication (0 until then).
        authorized: Whether the client has successfully authenticated.
        susp: Whether this remote is marked as suspicious (masquerade).
        reader: Stream reader for the TLS connection.
        writer: Stream writer for the TLS connection.
        client_v4: Assigned tunnel IPv4 address as an integer, if any.
        client_v6: Assigned tunnel IPv6 address as an integer, if any.
    """

    remote_id: int
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
        host_ipv4: IPv4 listen address.
        host_ipv6: IPv6 listen address; empty disables IPv6.
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

    def __init__(self, host_ipv4: str, host_ipv6: str, port: int, interface: str,
                 auth_handler: Callable[[int], tuple[bool, int]],
                 cert: str, key: str, *,
                 ipv6_prefix: str = "fd08::/64", proxy_ndp: bool = False,
                 ipv6_rotate_interval: int = 3600, masquerade: bool = False,
                 idle_callback: Callable[[], None] | None = None, idle_timer: int = 600):
        """Initialize the server.

        Args:
            host_ipv4: IPv4 listen address, e.g. ``"0.0.0.0"``.
            host_ipv6: IPv6 listen address, e.g. ``"::"``; empty disables
                the IPv6 listener.
            port: Listen port.
            interface: Physical egress interface used for NAT, e.g. ``"ens5"``.
            auth_handler: The handler of authentication, accepts a 128-bit
                authentication token as an integer and returns
                ``(success, remote_id)``.
            cert: Path to the TLS certificate file.
            key: Path to the TLS private key file.
            ipv6_prefix: IPv6 tunnel network in CIDR form. Defaults to the
                ULA ``fd08::/64``; use a global prefix (e.g. a provider
                routed ``/64``) to hand clients public IPv6 addresses.
            proxy_ndp: Proxy-NDP for client addresses on the physical
                interface. Needed for on-link IPv6 prefixes such as AWS
                EC2, where the instance owns a single /128 of the subnet.
            ipv6_rotate_interval: Seconds between reassigning each client
                a fresh random IPv6 address from the tunnel prefix
                (privacy rotation; default 3600, 0 disables; only applies
                to global prefixes — ULA/NAT66 never rotate).
            masquerade: Reply to bad auth with a fake success, then drop
                the connection's traffic (camouflage).
            idle_callback: Optional callable run when the server has had
                no clients for ``idle_timer`` seconds (e.g. auto-shutdown
                of an unused instance).
            idle_timer: Seconds without clients before ``idle_callback``
                fires (default 600).
        """
        self.host_ipv4 = host_ipv4
        self.host_ipv6 = host_ipv6
        self.port = port
        self.cert = cert
        self.key = key
        self.auth_handler = auth_handler
        self.masquerade = masquerade
        self.interface = interface
        # Stable IPv4 per remote id (a reconnect keeps the same address);
        # v4_cursor walks hosts 2..254 when handing out fresh addresses.
        self.id_v4: dict[int, int] = {}
        self.v4_cursor = 0
        self.proxy_ndp = proxy_ndp
        self.ipv6_net = ipaddress.IPv6Network(ipv6_prefix, strict=False)

        self.running = True
        self.remotes: list[Remote] = []
        self.tun: Tun | None = None
        self.addr_map: dict[tuple[int, int], Remote] = {}

        self.idle_callback = idle_callback
        self.idle_timer = idle_timer
        self.ipv6_rotate_interval = ipv6_rotate_interval

    async def ipv6_rotate_loop(self) -> None:
        """Reassign every connected client a new random IPv6 address periodically.

        Only runs for **global** tunnel prefixes. With a public prefix
        every client carries a stable public IPv6 identity; rotating it
        on ``ipv6_rotate_interval`` blurs that identity. NAT66/ULA
        prefixes never rotate: the client address is already hidden
        behind NAT, so a rotation would only drop connections for no
        privacy gain. The address is replaced, not added, so existing
        connections drop at each rotation (the privacy trade-off of a
        rotating public IP). Set the interval to 0 to disable rotation.
        """
        if not self.ipv6_rotate_interval or self.ipv6_net.prefixlen >= 128 \
                or not self.ipv6_net.is_global:
            return
        while self.running:
            await asyncio.sleep(self.ipv6_rotate_interval)
            for remote in list(self.remotes):
                if remote.client_v6 is None or remote.writer.is_closing():
                    continue
                old_v6 = remote.client_v6
                new_v6 = self._random_v6()
                self.addr_map.pop((6, old_v6), None)
                self.addr_map[(6, new_v6)] = remote
                remote.client_v6 = new_v6
                if self.proxy_ndp and self.ipv6_net.is_global and self.tun is not None:
                    self.tun.teardown_proxy_ndp(str(ipaddress.IPv6Address(old_v6)))
                    self.tun.setup_proxy_ndp(self.interface, str(ipaddress.IPv6Address(new_v6)))
                remote.writer.write(IPv6Assign(new_v6, self.ipv6_net.prefixlen).pack())
                await remote.writer.drain()
                rich.print(f"[yellow]Renewed {remote.remote_id} IPv6 -> {ipaddress.IPv6Address(new_v6)}[/yellow]")

    def _random_v6(self) -> int:
        """Pick a random unused address from the tunnel prefix.

        Excludes the network address, the server's own address
        (``network + 1``) and any address currently assigned to a client.

        Raises:
            ValueError: If the prefix has no host bits to draw from.
        """
        network = int(self.ipv6_net.network_address)
        if self.ipv6_net.prefixlen >= 128:
            raise ValueError("tunnel prefix has no host bits for client addresses")
        while True:
            candidate = network | random.getrandbits(128 - self.ipv6_net.prefixlen)
            if candidate == network or candidate == network + 1:
                continue
            if (6, candidate) not in self.addr_map:
                return candidate

    def _assign_v4(self) -> int:
        """Pick a free IPv4 client address from 10.8.0.0/24 (hosts 2..254).

        Raises:
            RuntimeError: If every host is currently assigned (253
                concurrent clients).
        """
        base = 0xA080000
        for _ in range(253):
            host = 2 + self.v4_cursor
            self.v4_cursor = (self.v4_cursor + 1) % 253
            candidate = base | host
            if (4, candidate) not in self.addr_map:
                return candidate
        raise RuntimeError("IPv4 tunnel network exhausted (10.8.0.0/24 full)")

    async def idle_scan(self) -> None:
        """Invoke ``idle_callback`` whenever the server has had no clients for ``idle_timer`` seconds.

        Polls cheaply (1s while clients are connected) and sleeps the full
        idle window only while the server is empty, so the callback fires
        only after a continuous idle period. After the callback returns
        the scan re-arms, so a callback that declines to act (e.g. a
        repair-mode guard that skips the shutdown) lets the check run
        again after the next idle window. The callback must return
        quickly — it runs on the event loop (blocking work should spawn
        its own thread/task).
        """
        if not self.idle_callback:
            return
        while self.running:
            if self.remotes:
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(self.idle_timer)
            if self.running and not self.remotes:
                self.idle_callback()

    async def handle_remote(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve one client connection: read, dispatch and reply to packets until disconnect.

        Args:
            reader: Stream reader for the accepted TLS connection.
            writer: Stream writer for the accepted TLS connection.
        """
        peer_addr = writer.get_extra_info("peername")
        rich.print(f"[green]New connection from {peer_addr}[/green]")
        remote = Remote(0, False, False, reader, writer)
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
        if remote in self.remotes:
            self.remotes.remove(remote)
        if remote.client_v4 is not None and self.addr_map.get((4, remote.client_v4)) is remote:
            # Only release the address if we still own it: with stable
            # per-id addresses a newer connection may already hold it.
            self.addr_map.pop((4, remote.client_v4), None)
        if remote.client_v6 is not None:
            self.addr_map.pop((6, remote.client_v6), None)
            if self.proxy_ndp and self.tun is not None:
                self.tun.teardown_proxy_ndp(str(ipaddress.IPv6Address(remote.client_v6)))
        # Closing can race with the peer's TLS shutdown (e.g. application
        # data after close_notify) or a hard reset; the connection is being
        # torn down anyway, so close errors are not worth propagating.
        try:
            remote.writer.close()
            await remote.writer.wait_closed()
        except OSError:
            pass

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
            success, remote_id = self.auth_handler(packet.token)
            if not success:
                if not self.masquerade:
                    return [AuthenticationResponse(False, 0)]
                remote.susp = True
                print(f"Susp remote: {remote}")
            remote.authorized = True
            remote.remote_id = remote_id
            # IPv4 is stable per remote id: a reconnect with the same id
            # gets the same address back (id_v4 caches the assignment);
            # masqueraded connections get a throwaway address, never cached.
            if success:
                client_ip = self.id_v4.get(remote_id)
                if client_ip is None:
                    client_ip = self._assign_v4()
                    self.id_v4[remote_id] = client_ip
            else:
                client_ip = self._assign_v4()
            # Flat tunnel networks behind the gateway TUN: IPv4 10.8.0.0/24
            # (server 10.8.0.1, clients 10.8.0.N); IPv6 prefix configurable
            # (default ULA fd08::/64, or a public prefix for global addresses).
            client_v6 = self._random_v6()
            self.addr_map[(4, client_ip)] = remote
            self.addr_map[(6, client_v6)] = remote
            if self.proxy_ndp and self.ipv6_net.is_global and self.tun is not None:
                # On-link prefixes (AWS EC2): answer NDP for the client's
                # global address on the physical interface.
                self.tun.setup_proxy_ndp(self.interface, str(ipaddress.IPv6Address(client_v6)))
            remote.client_v4 = client_ip
            remote.client_v6 = client_v6

            return [
                AuthenticationResponse(True, remote.remote_id),
                IPv4Assign(client_ip, 24),
                IPv6Assign(client_v6, self.ipv6_net.prefixlen),
            ]
        if isinstance(packet, ApplicationData):
            if not self.tun:
                return []

            self.tun.write(packet.data)
            return []
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
        asyncio.create_task(self.idle_scan())
        asyncio.create_task(self.ipv6_rotate_loop())

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(self.cert, self.key)

        # Bind one listener per family. The IPv6 socket must be V6ONLY so it
        # can coexist with a wildcard IPv4 listener on the same port (Linux
        # defaults to bindv6only=0, where a bare "::" bind would conflict).
        servers: list[asyncio.AbstractServer] = []
        if self.host_ipv4:
            servers.append(await asyncio.start_server(
                self.handle_remote, self.host_ipv4, self.port, ssl=ssl_ctx,
            ))
            rich.print(f"[green]Server listening on {self.host_ipv4}:{self.port} (v4)[/green]")
        if self.host_ipv6:
            sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host_ipv6, self.port))
            servers.append(await asyncio.start_server(
                self.handle_remote, sock=sock, ssl=ssl_ctx,
            ))
            rich.print(f"[green]Server listening on {self.host_ipv6}:{self.port} (v6)[/green]")

        try:
            await asyncio.gather(*(server.serve_forever() for server in servers))
        finally:
            for server in servers:
                server.close()
                await server.wait_closed()

    def kick(self, remote_id: int) -> bool:
        """Close the connection of the client carrying ``remote_id``.

        Args:
            remote_id: The client id returned by ``auth_handler``.

        Returns:
            True if a matching client was found and kicked.
        """
        for remote in self.remotes:
            if remote.remote_id == remote_id:
                remote.writer.close()
                return True
        return False

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
