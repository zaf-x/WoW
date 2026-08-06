"""Daemon mode: exposes a JSON-lines management port on 127.0.0.1.

Requests (one JSON object per line):
  {"cmd": "connect", "host": "…", "port": 443, "token": "<hex>"}
  {"cmd": "disconnect"}
  {"cmd": "status"}
  {"cmd": "shutdown"}

Responses: {"ok": true, ...} / {"ok": false, "error": "..."}

Events broadcast to all management sessions:
  {"event": "state", "state": "disconnected|connecting|connected", ...}
  {"event": "stats", "up_bytes": N, "down_bytes": M}
  {"event": "log", "line": "..."}

The port is bound to localhost only; there is no authentication — any local
process can control the daemon (same threat model as e.g. clash's external
controller).
"""

from __future__ import annotations

import asyncio
import json
import logging

from .client import Client, parse_token

logger = logging.getLogger(__name__)


class _BroadcastLogHandler(logging.Handler):
    """Forward log records to all management sessions."""

    def __init__(self, daemon: "Daemon") -> None:
        super().__init__()
        self.daemon = daemon

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.daemon.broadcast({"event": "log", "line": self.format(record)})
        except Exception:
            pass


class Daemon:
    def __init__(self, tun_name: str = "wow0", fwmark: int = 0x1, mgmt_port: int = 7891) -> None:
        self.tun_name = tun_name
        self.fwmark = fwmark
        self.mgmt_port = mgmt_port
        self.state = "disconnected"
        self.tunnel_ip: str | None = None
        self.server_addr: str | None = None
        self.error: str | None = None
        self.client: Client | None = None
        self.client_task: asyncio.Task | None = None
        self.sessions: set[asyncio.StreamWriter] = set()
        self.server: asyncio.AbstractServer | None = None
        self._shutdown = asyncio.Event()
        self._manual_disconnect = False
        self._connect_params: tuple[str, int, int] | None = None

    # ---- lifecycle ----

    async def run(self, autoconnect: tuple[str, int, int] | None = None) -> None:
        handler = _BroadcastLogHandler(self)
        handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        logging.getLogger().addHandler(handler)
        stats_task = asyncio.create_task(self._stats_loop())
        try:
            self.server = await asyncio.start_server(self._handle_session, "127.0.0.1", self.mgmt_port)
            logger.info("Management port listening on 127.0.0.1:%d", self.mgmt_port)
            if autoconnect:
                host, port, token = autoconnect
                await self._connect(host, port, token)
            await self._shutdown.wait()
        finally:
            stats_task.cancel()
            await self._disconnect()
            if self.server:
                self.server.close()
                await self.server.wait_closed()
            for w in list(self.sessions):
                w.close()
            logging.getLogger().removeHandler(handler)
            logger.info("Daemon stopped")

    # ---- management sessions ----

    async def _handle_session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.sessions.add(writer)
        self._send(writer, self._state_event())
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    req = json.loads(line)
                except json.JSONDecodeError:
                    self._send(writer, {"ok": False, "error": "invalid JSON"})
                    continue
                resp = await self._dispatch(req)
                if resp is not None:
                    self._send(writer, resp)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.sessions.discard(writer)
            writer.close()

    async def _dispatch(self, req: dict) -> dict | None:
        cmd = req.get("cmd")
        if cmd == "connect":
            try:
                host = str(req["host"])
                port = int(req["port"])
                token = parse_token(str(req["token"]))
            except (KeyError, ValueError) as e:
                return {"ok": False, "error": f"bad connect params: {e}"}
            return await self._connect(host, port, token)
        if cmd == "disconnect":
            await self._disconnect()
            return {"ok": True}
        if cmd == "status":
            return {"ok": True, **self._status()}
        if cmd == "shutdown":
            asyncio.get_running_loop().call_soon(self._shutdown.set)
            return {"ok": True}
        return {"ok": False, "error": f"unknown cmd {cmd!r}"}

    # ---- client management ----

    async def _connect(self, host: str, port: int, token: int) -> dict:
        if self.client_task and not self.client_task.done():
            return {"ok": False, "error": "already connected or connecting"}
        self.error = None
        self.server_addr = f"{host}:{port}"
        self._manual_disconnect = False
        self._connect_params = (host, port, token)
        self.client_task = asyncio.create_task(self._reconnect_loop())
        return {"ok": True}

    async def _reconnect_loop(self) -> None:
        """掉线自动重连，指数退避 1s -> 30s 封顶；手动断开则退出。"""
        backoff = 1.0
        while not self._manual_disconnect:
            assert self._connect_params is not None
            host, port, token = self._connect_params
            self.client = Client(host, port, token, self.tun_name, self.fwmark, on_state=self._on_state)
            try:
                await self.client.run()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Client error: %s", e)
                self.error = str(e)
                self._on_state("disconnected", error=str(e))
            if self._manual_disconnect:
                break
            logger.info("Reconnecting in %.0fs...", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _disconnect(self) -> None:
        self._manual_disconnect = True
        if self.client_task and not self.client_task.done():
            self.client_task.cancel()
            try:
                await self.client_task
            except asyncio.CancelledError:
                pass
        self.client_task = None
        self.client = None

    def _on_state(self, state: str, info: dict) -> None:
        self.state = state
        self.tunnel_ip = info.get("tunnel_ip") if state == "connected" else None
        self.broadcast(self._state_event())

    # ---- events / stats ----

    def _state_event(self) -> dict:
        ev = {"event": "state", "state": self.state}
        if self.tunnel_ip:
            ev["tunnel_ip"] = self.tunnel_ip
        if self.server_addr:
            ev["server"] = self.server_addr
        if self.error:
            ev["error"] = self.error
        return ev

    def _status(self) -> dict:
        st = self._state_event()
        st.pop("event")
        st["up_bytes"] = self.client.up_bytes if self.client else 0
        st["down_bytes"] = self.client.down_bytes if self.client else 0
        return st

    async def _stats_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            if self.client and self.state == "connected":
                self.broadcast(
                    {
                        "event": "stats",
                        "up_bytes": self.client.up_bytes,
                        "down_bytes": self.client.down_bytes,
                    }
                )

    # ---- io helpers ----

    def broadcast(self, msg: dict) -> None:
        for w in list(self.sessions):
            self._send(w, msg)

    @staticmethod
    def _send(writer: asyncio.StreamWriter, msg: dict) -> None:
        try:
            writer.write(json.dumps(msg).encode() + b"\n")
        except (ConnectionError, RuntimeError):
            pass
