"""``reframe-server`` / ``python -m reframe_server``: uvicorn with one worker. In desktop mode
the first stdout line is ``{"event":"ready","port":N}`` once the server listens; every log
line goes to stderr, so stdout stays readable for the desktop shell."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import uvicorn
from pydantic import ValidationError

from reframe_server import __version__, idle, owner, parent, security
from reframe_server.app import create_app
from reframe_server.config import ServerConfig

__all__ = ["main", "ready_line", "serve"]

_SHUTDOWN_GRACE = 2
"""Seconds uvicorn waits for open connections at shutdown before the lifespan closes the
facade anyway. The desktop shell kills the server 5 s after it asked it to stop."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reframe-server",
        description="The Reframe web server. Every option can also be set as REFRAME_<NAME>.",
    )
    parser.add_argument("--version", action="version", version=f"reframe-server {__version__}")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--mode", choices=["web", "desktop"])
    parser.add_argument("--auth", choices=["none", "token", "password"])
    parser.add_argument("--media-root", dest="media_roots", action="append", type=Path)
    parser.add_argument("--output-root", dest="output_roots", action="append", type=Path)
    parser.add_argument("--owner-only", action="store_true", default=None)
    parser.add_argument("--idle-exit", type=float, metavar="SECONDS")
    parser.add_argument("--parent-pid", type=int, metavar="PID")
    parser.add_argument(
        "--set-password", action="store_true", help="set the login password and exit"
    )
    return parser


def ready_line(port: int) -> str:
    return json.dumps({"event": "ready", "port": port}, separators=(",", ":"))


def _log_config() -> dict[str, Any]:
    config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    for handler in config["handlers"].values():
        handler["stream"] = "ext://sys.stderr"
    return config


async def serve(config: ServerConfig) -> int:
    """Run the server until it is stopped. Returns the exit code: 0, or when it never started
    ``app.state.exit_code`` (1, or 75 for ``owner_only``)."""
    app = create_app(config)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=config.host,
            port=config.port,
            log_config=_log_config(),
            # uvicorn waits for every connection to close before the lifespan runs, and a
            # client that does not read never lets its connection close.
            timeout_graceful_shutdown=_SHUTDOWN_GRACE,
        )
    )

    def request_shutdown() -> None:
        server.should_exit = True

    app.state.request_shutdown = request_shutdown
    watch = None
    if config.parent_pid is not None:
        loop = asyncio.get_running_loop()
        watch = parent.watch_parent(config.parent_pid, request_shutdown, loop)
        if watch is None:
            print(
                f"reframe-server: the parent process {config.parent_pid} is not running",
                file=sys.stderr,
            )
            return 1

    async def run_server() -> None:
        # uvicorn ends a failed lifespan start-up or bind with sys.exit(3) inside this task;
        # the exit code is app.state.exit_code instead.
        with contextlib.suppress(SystemExit):
            await server.serve()

    idle_watch: asyncio.Task[None] | None = None
    try:
        running = asyncio.create_task(run_server())
        while not server.started and not running.done():  # noqa: ASYNC110 - uvicorn has no event
            await asyncio.sleep(0.02)
        if server.started:
            port = server.servers[0].sockets[0].getsockname()[1]
            owner.publish(app, port)
            if config.idle_exit is not None:
                idle_watch = asyncio.create_task(
                    idle.watch(app, config.idle_exit, request_shutdown)
                )
            if config.mode == "desktop":
                print(ready_line(port), flush=True)
        await running
    finally:
        if idle_watch is not None:
            idle_watch.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await idle_watch
        if watch is not None:
            watch.close()
    return 0 if server.started else int(app.state.exit_code)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    given = {
        name: value
        for name, value in vars(args).items()
        if value is not None and name != "set_password"
    }
    try:
        config = ServerConfig(**given)
    except ValidationError as exc:
        for error in exc.errors():
            print(f"reframe-server: {error['msg']}", file=sys.stderr)
        return 2
    if args.set_password:
        return security.set_password_interactive(config)
    try:
        return asyncio.run(serve(config))
    except KeyboardInterrupt:  # uvicorn re-raises the signal after its clean shutdown
        return 130


if __name__ == "__main__":
    sys.exit(main())
