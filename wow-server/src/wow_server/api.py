"""FastAPI management API for the WoW VPN server, embedded on the same event loop.

The API routes run as coroutines on the same asyncio loop as the VPN
server itself, so they can read and mutate :class:`Server` state directly
without locks (single-threaded cooperative scheduling). Bind the app to
loopback unless an ``api_token`` is set — it has full control over the
running server.
"""

import ipaddress
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Depends as DependsParam
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .server import Remote, Server
from .__about__ import __version__


class API:
    """Management API bound to a running :class:`Server`.

    Attributes:
        server: The VPN server being managed.
        token: Optional bearer token; when non-empty every request must
            present ``Authorization: Bearer <token>``.
        app: The constructed FastAPI application (pass to uvicorn).
    """

    def __init__(self, server: Server, token: str = "", cors: str = "*") -> None:
        """Build the FastAPI application around ``server``.

        Args:
            server: The running VPN server to manage.
            token: Optional bearer token; empty means no authentication
                (the API should then only be bound to loopback).
            cors: Comma-separated list of allowed browser origins for the
                management API; ``*`` allows any origin (the bearer token
                stays the only credential).
        """
        self.server = server
        self.token = token
        self.app = FastAPI(title="wow-server API", version=__version__)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in cors.split(",") if o.strip()],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Routes that require the token (when configured) share one dependency.
        deps: list[DependsParam] = []
        if token:
            deps = [Depends(self._require_auth)]

        @self.app.get("/health")
        async def health() -> dict[str, Any]:
            """Return whether the VPN server is still running."""
            return {"ok": True, "running": self.server.running}

        @self.app.get("/clients", dependencies=deps)
        async def clients() -> list[dict[str, Any]]:
            """List the currently connected clients."""
            return [self._client_info(remote) for remote in self.server.remotes]

        @self.app.post("/clients/{remote_id}/kick", dependencies=deps)
        async def kick(remote_id: str) -> dict[str, Any]:
            """Disconnect the client carrying ``remote_id`` (hex string)."""
            try:
                rid = int(remote_id, 16)
            except ValueError:
                raise HTTPException(status_code=422, detail="invalid remote_id")
            if not self.server.kick(rid):
                raise HTTPException(status_code=404, detail="client not found")
            return {"ok": True}

        @self.app.get("/stats", dependencies=deps)
        async def stats() -> dict[str, Any]:
            """Return server-wide counters and configuration."""
            return {
                "clients": len(self.server.remotes),
                "addr_map_size": len(self.server.addr_map),
                "v4_assignments": len(self.server.id_v4),
                "tun_up": self.server.tun is not None,
                "idle_timer": self.server.idle_timer,
                "ipv6_rotate_interval": self.server.ipv6_rotate_interval,
                "ipv6_prefix": str(self.server.ipv6_net),
                "version": __version__,
            }

    async def _require_auth(
        self, creds: HTTPAuthorizationCredentials | None = Depends(
            HTTPBearer(auto_error=False)
        )
    ) -> None:
        """FastAPI dependency: reject requests without a valid bearer token."""
        if creds is None or creds.credentials != self.token:
            raise HTTPException(status_code=401, detail="invalid or missing token")

    @staticmethod
    def _client_info(remote: Remote) -> dict[str, Any]:
        """Serialize one client connection for the API response."""
        peer = None
        try:
            peer = remote.writer.get_extra_info("peername")
        except Exception:
            peer = None
        return {
            # Sent as a hex string: remote ids are up to 128 bits, which
            # exceeds the JSON-safe integer range (2^53) in JavaScript.
            "remote_id": f"{remote.remote_id:x}",
            "authorized": remote.authorized,
            "susp": remote.susp,
            "ipv4": (
                str(ipaddress.IPv4Address(remote.client_v4))
                if remote.client_v4 is not None
                else None
            ),
            "ipv6": (
                str(ipaddress.IPv6Address(remote.client_v6))
                if remote.client_v6 is not None
                else None
            ),
            "peer": peer,
        }
