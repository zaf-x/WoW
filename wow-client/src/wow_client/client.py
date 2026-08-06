from __future__ import annotations

import argparse
import asyncio
import ipaddress
import logging
import signal
import socket
import ssl
import struct
import time
from collections.abc import Callable
from typing import Any

from wow_common.protocol import (  # type: ignore
    ApplicationData,
    Authentication,
    AuthenticationResponse,
    PacketType,
    Ping,
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
        on_state: "Callable[..., None] | None" = None,
    ) -> None:
        self.host = host
        self.port = port
        self.token = token
        self.tun_name = tun_name
        self.fwmark = fwmark
        self.on_state = on_state
        self.state = "disconnected"
        self.tunnel_ip: str | None = None
        self.up_bytes = 0
        self.down_bytes = 0
        self._last_rx = 0.0

    async def _heartbeat(self, writer: asyncio.StreamWriter, interval: float, timeout: float) -> None:
        """定期发 PING 保活；超过 timeout 没收到任何包就判定连接已死，主动断开。

        跨越 NAT/GFW 的 TCP 空闲连接会被中间设备静默丢弃，必须靠应用层
        心跳维持映射并检测死连接。
        """
        while True:
            await asyncio.sleep(interval)
            try:
                writer.write(Ping().pack())
                await writer.drain()
            except ConnectionError:
                return
            if time.monotonic() - self._last_rx > timeout:
                logger.warning("No packet from server for %.0fs, connection presumed dead", timeout)
                writer.transport.abort()

    def _set_state(self, state: str, **info: dict[str, Any]) -> None:
        self.state = state
        if state == "connected":
            self.tunnel_ip = info.get("tunnel_ip")
        elif state == "disconnected":
            self.tunnel_ip = None
        if self.on_state:
            self.on_state(state, info)

    async def _connect(self, ssl_ctx: ssl.SSLContext):
        # 自建 socket 并打 SO_MARK，配合 ip rule 使 VPN 自身流量不进 TUN，避免环路
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, self.fwmark)
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        await loop.sock_connect(sock, (self.host, self.port))
        return await asyncio.open_connection(sock=sock, ssl=ssl_ctx, server_hostname=self.host)

    async def run(self) -> None:
        self._set_state("connecting", host=self.host, port=self.port)
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
        self._set_state("connected", tunnel_ip=addr, host=self.host, port=self.port)

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
                    self.up_bytes += len(data)
                    writer.write(ApplicationData(data).pack())

            loop.add_reader(tun.fileno(), on_tun_readable)
            self._last_rx = time.monotonic()
            hb_task = asyncio.create_task(self._heartbeat(writer, interval=15, timeout=45))
            try:
                while True:
                    pkt_type, body = await read_packet(reader)
                    self._last_rx = time.monotonic()
                    if pkt_type == PacketType.APP_DATA:
                        self.down_bytes += len(body)
                        tun.write(body)
                    elif pkt_type in (PacketType.PING, PacketType.PONG):
                        pass  # 心跳包，_last_rx 已更新
                    else:
                        logger.warning("Unexpected packet type %d, ignored", pkt_type)
            finally:
                hb_task.cancel()
        except (asyncio.IncompleteReadError, ConnectionError):
            logger.info("Connection closed")
        finally:
            loop.remove_reader(tun.fileno())
            tun.teardown_dns()
            tun.teardown_routing()
            tun.close()
            writer.close()
            await writer.wait_closed()
            self._set_state("disconnected")


def parse_token(text: str) -> int:
    value = int(text, 16)
    if value.bit_length() > 128:
        raise ValueError("Token must fit in 128 bits (16 bytes)")
    return value


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="WoW VPN client")
    parser.add_argument("host", nargs="?")
    parser.add_argument("port", nargs="?", type=int)
    parser.add_argument("token", nargs="?", type=parse_token, help="128-bit auth token (hex)")
    parser.add_argument("--tun", default="wow0", help="TUN device name (default: wow0)")
    parser.add_argument(
        "--fwmark",
        type=lambda s: int(s, 0),
        default=0x1,
        help="SO_MARK/fwmark value for the VPN's own traffic (default: 0x1)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="run as daemon exposing a JSON-lines management port on 127.0.0.1",
    )
    parser.add_argument("--mgmt-port", type=int, default=7891, help="management port (default: 7891)")
    args = parser.parse_args()

    task: asyncio.Task
    if args.daemon:
        from .daemon import Daemon

        autoconnect = None
        if args.host and args.port and args.token is not None:
            autoconnect = (args.host, args.port, args.token)
        task = asyncio.create_task(
            Daemon(args.tun, args.fwmark, args.mgmt_port).run(autoconnect)
        )
    else:
        if not (args.host and args.port and args.token is not None):
            parser.error("host/port/token are required unless --daemon is given")
        client = Client(args.host, args.port, args.token, args.tun, args.fwmark)
        task = asyncio.create_task(client.run())
    # SIGTERM/SIGINT 时取消主任务，让 finally 清理路由和 DNS
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
