"""Command-line entry point for the WoW VPN server."""

import asyncio
import contextlib
import logging
from collections.abc import Generator

import uvicorn

from . import config
from .api import API
from .server import Server


class _EmbeddedServer(uvicorn.Server):
    """uvicorn server that never installs its own signal handlers.

    uvicorn >= 0.30 removed the ``install_signal_handlers`` constructor flag:
    ``serve()`` now unconditionally replaces the SIGINT/SIGTERM handlers on the
    main thread via ``capture_signals()``. When embedded on the VPN server's own
    loop that would swallow Ctrl+C (and systemd's SIGTERM), so override it with a
    no-op; graceful shutdown still works because ``main()`` sets ``should_exit``.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None, None, None]:
        yield


def main() -> None:
    """Run the server until interrupted."""
    args = config.parse_args()
    cfg = config.Config(args.config)
    cfg.load()
    logging.basicConfig(
        level=logging.DEBUG if cfg.verbose else logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    server = Server(**cfg.get_kwargs())

    async def run() -> None:
        """Run the VPN server and, when enabled, the management API on the same loop."""
        api_task = None
        uvicorn_server = None
        api_kw = cfg.get_api_kwargs()
        if api_kw["port"]:
            api = API(server, token=api_kw["token"])
            uvicorn_config = uvicorn.Config(
                api.app, host=api_kw["host"], port=api_kw["port"], log_level="warning"
            )
            uvicorn_server = _EmbeddedServer(uvicorn_config)
            api_task = asyncio.create_task(uvicorn_server.serve())

        try:
            await server.serve()
        finally:
            if uvicorn_server is not None:
                uvicorn_server.should_exit = True
            if api_task is not None:
                await asyncio.gather(api_task, return_exceptions=True)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
