import asyncio
import ssl
from wow_common.protocol import ApplicationData, Authentication, AuthenticationResponse, Ping, unpack  # type: ignore
from wow_common.tun import Tun # type: ignore
import socket
import ipaddress
import rich

def human_size(size: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if abs(size) < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} EB"

class Client:
    def __init__(self, server_host: str, server_port: int, token: str, fwmark: int = 0x1):
        self.server_host = server_host
        self.server_port = server_port
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

    async def run(self):
        rich.print(f"[bold]Client started[/bold]")
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        loop = asyncio.get_running_loop()
        await loop.sock_connect(self.sock, (self.server_host, self.server_port))
        rich.print(f"[green]Connected[/green]")

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

        rich.print("[green]Authenticated[/green]")

        self.ip_addr = ipaddress.IPv4Address(ip)
        self.tun = Tun("wowtun")
        self.tun.up()
        self.tun.set_addr(f"{self.ip_addr}/{self.cidr}")
        self.tun.setup_routing(self.fwmark, bypass_ip=self.server_host)
        self.tun.setup_dns()
        rich.print("[green]TUN setup finished[/green]")

        loop.add_reader(self.tun.fileno(), self.manage_new_data)
        asyncio.create_task(self.send_data_loop())
        asyncio.create_task(self.ping_loop())
        while self.running:
            pkt = await self.read_packet()
            if isinstance(pkt, ApplicationData):
                self.tun.write(pkt.data)
                self.downlink_d += len(pkt.data)
            await self.writer.drain()
        self.writer.close()
        await self.writer.wait_closed()
        self.writer = None
        self.reader = None

    async def ping_loop(self):
        while self.running:
            if not self.writer:
                break
            self.writer.write(Ping().pack())
            print("\033[2K",end="")
            rich.print(f"[bold]Uplink data: {human_size(self.uplink_d)} Downlink data: {human_size(self.downlink_d)}[/bold]", end="\r")
            await self.writer.drain()
            await asyncio.sleep(5)

    async def stop(self):
        if not self.tun:
            return
        rich.print("\n")
        rich.print("[yellow]Stopping[/yellow]")
        self.running = False
        self.tun.teardown_routing()
        self.tun.teardown_dns()
        self.tun.close()
        loop = asyncio.get_running_loop()
        loop.remove_reader(self.tun.fileno())
        rich.print("Stopped")

    async def read_packet(self):
        if not self.reader:
            raise ValueError("not connected yet")
        length = await self.reader.readexactly(4)
        data = await self.reader.readexactly(int.from_bytes(length, "big"))
        return unpack(length + data)

    def manage_new_data(self):
        if not self.tun or not self.writer:
            return
        data = self.tun.read()
        self.pending.put_nowait(data)

    async def send_data_loop(self):
        while self.running:
            data = await self.pending.get()
            if not self.writer:
                break

            self.writer.write(ApplicationData(data).pack())
            self.uplink_d += len(data)
            await self.writer.drain()