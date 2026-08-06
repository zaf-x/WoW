from dataclasses import dataclass
import ipaddress
import logging
import asyncio
import ssl
from wow_common.protocol import unpack, PacketType, Authentication, AuthenticationResponse, ApplicationData, Ping, Pong  # type: ignore
from wow_common.tun import Tun # type: ignore
import uuid

@dataclass
class Remote:
    stream_id: str
    authorized: bool
    tun: Tun | None

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

class Server:
    def __init__(self, host: str, port: int, token: int, interface: str, cert: str, key: str, masquerade: bool = False):
        self.host = host
        self.port = port
        self.cert = cert
        self.key = key
        self.token = token
        self.masquerade = masquerade
        self.interface = interface
        self.ip_cnt = 2

    async def handle_stream(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer_addr = writer.get_extra_info("peername")
        logging.info(f"New connection from {peer_addr}")
        remote = Remote(uuid.uuid4().hex, False, None, reader, writer)

        try:
            while True:
                # 精确读取 4 字节长度头
                length_bytes = await reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")

                # 精确读取 payload
                data = await reader.readexactly(length)

                packet = unpack(length_bytes + data)

                ret = await self.manage_packet(remote, packet)
                if ret:
                    writer.write(ret.pack())
                await writer.drain()

        except asyncio.IncompleteReadError:
            logging.info(f"Client {peer_addr} disconnected")
        except Exception:
            logging.exception(f"Unhandled exception from {peer_addr}")
        finally:
            if remote.tun is not None:
                asyncio.get_running_loop().remove_reader(remote.tun.fileno())
                remote.tun.teardown_nat()
                remote.tun.close()
                remote.tun = None
            writer.close()

    async def manage_packet(self, remote: Remote, packet: PacketType):
        if isinstance(packet, Authentication):
            if packet.token != self.token:
                if not self.masquerade:
                    return AuthenticationResponse(False, 0, 0)
                return
            remote.authorized = True
            remote.tun = Tun(f"vpntun{remote.stream_id[:5]}")
            remote.tun.up()
            remote.tun.setup_nat(self.interface)
            loop = asyncio.get_running_loop()
            loop.add_reader(remote.tun.fileno(), lambda: self.on_tun_readable(remote))
            self.ip_cnt += 1
            client_ip = 0b00001010000010000000000000000000 | self.ip_cnt
            client_addr = str(ipaddress.IPv4Address(client_ip))
            remote.tun.add_route(f"{client_addr}/32")
            remote.tun.set_addr("10.8.0.1/24")
            
            return AuthenticationResponse(True, client_ip, 24)
        if isinstance(packet, ApplicationData):
            if not remote.tun:
                return

            remote.tun.write(packet.data)
        if isinstance(packet, Ping):
            return Pong()

    async def serve(self) -> None:
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(self.cert, self.key)

        server = await asyncio.start_server(
            self.handle_stream,
            self.host,
            self.port,
            ssl=ssl_ctx,
        )
        logging.info(f"Server listening on {self.host}:{self.port}")

        async with server:
            await server.serve_forever()

    def on_tun_readable(self, remote: Remote):
        if remote.tun is None or remote.writer.is_closing():
            return
        data = remote.tun.read()
        packet = ApplicationData(data)
        remote.writer.write(packet.pack())