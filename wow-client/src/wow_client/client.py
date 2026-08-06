from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import signal
import socket
import ssl
import struct

from wow_common.protocol import (  # type: ignore
    ApplicationData,
    Authentication,
    AuthenticationResponse,
    PacketType,
)
from wow_common.tun import Tun  # type: ignore

logger = logging.getLogger(__name__)


async def read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(5)
    payload_len, pkt_type = struct.unpack("!IB", header)
    body = await reader.readexactly(payload_len - 1)
    return pkt_type, body


class Client:
    def __init__(
        self,
        host: str,
        port: int,
        token: int,
        tun_name: str = "wow0",
        fwmark: int = 0x1,
    ) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.tun_name = tun_name
        self.fwmark = fwmark

    async def _connect(self, ssl_ctx: ssl.SSLContext):
        # 自建 socket 并打 SO_MARK，配合 ip rule 使 VPN 自身流量不进 TUN，避免环路
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, self.fwmark)
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        await loop.sock_connect(sock, (self.host, self.port))
        return await asyncio.open_connection(sock=sock, ssl=ssl_ctx, server_hostname=self.host)

    async def run(self) -> None:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE  # 自签名证书，跳过校验

        reader, writer = await self._connect(ssl_ctx)
        logger.info("Connected to %s:%d", self.host, self.port)

        writer.write(Authentication(self.token).pack())
        await writer.drain()

        pkt_type, body = await read_packet(reader)
        if pkt_type != PacketType.AUTH_RESP:
            raise RuntimeError(f"Expected AUTH_RESP, got type {pkt_type}")
        resp = AuthenticationResponse.unpack(struct.pack("!IB", len(body) + 1, pkt_type) + body)
        if not resp.success:
            raise PermissionError("Authentication failed")
        addr = f"{ipaddress.IPv4Address(resp.ip_addr)}/{resp.ip_cidr}"
        logger.info("Authenticated, assigned address %s", addr)

        tun = Tun(self.tun_name)
        loop = asyncio.get_running_loop()
        try:
            tun.set_addr(addr)
            tun.up()
            tun.setup_routing(self.fwmark, bypass_ip=self.host)
            tun.setup_dns()

            def on_tun_readable() -> None:
                data = tun.read()
                if data:
                    writer.write(ApplicationData(data).pack())

            loop.add_reader(tun.fileno(), on_tun_readable)
            while True:
                pkt_type, body = await read_packet(reader)
                if pkt_type == PacketType.APP_DATA:
                    tun.write(body)
                else:
                    logger.warning("Unexpected packet type %d, ignored", pkt_type)
        except (asyncio.IncompleteReadError, ConnectionError):
            logger.info("Connection closed")
        finally:
            loop.remove_reader(tun.fileno())
            tun.teardown_dns()
            tun.teardown_routing()
            tun.close()
            writer.close()
            await writer.wait_closed()


def parse_token(text: str) -> int:
    value = int(text, 16)
    if value.bit_length() > 128:
        raise ValueError("Token must fit in 128 bits (16 bytes)")
    return value


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="WoW VPN client")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("token", type=parse_token, help="128-bit auth token (hex)")
    parser.add_argument("--tun", default="wow0", help="TUN device name (default: wow0)")
    parser.add_argument(
        "--fwmark",
        type=lambda s: int(s, 0),
        default=0x1,
        help="SO_MARK/fwmark value for the VPN's own traffic (default: 0x1)",
    )
    args = parser.parse_args()

    client = Client(args.host, args.port, args.token, args.tun, args.fwmark)
    task = asyncio.create_task(client.run())
    # SIGTERM/SIGINT 时取消主任务，让 run() 的 finally 清理路由和 DNS
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
