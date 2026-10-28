"""The server that owns the queue (decision 0042): it opens the queue at start-up, publishes
``server.json`` once it listens, and removes it at close. With ``owner_only`` a server that
cannot own the queue does not start."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from reframe.models import ServerEndpoint

__all__ = [
    "ENDPOINT_FILE",
    "EXIT_STORE_BUSY",
    "ServerEndpoint",
    "StoreBusy",
    "publish",
    "start",
    "withdraw",
]

ENDPOINT_FILE = "server.json"
EXIT_STORE_BUSY = 75
"""The exit code of ``--owner-only`` when another process owns the queue (``EX_TEMPFAIL``)."""


class StoreBusy(Exception):
    """``owner_only``, and another process owns the queue: the server does not start."""


def start(app: FastAPI) -> None:
    """Called by the lifespan once the facade exists (``app.state.reframe``): open the queue.
    When another process owns it and ``config.owner_only`` is set, set ``app.state.exit_code``
    to :data:`EXIT_STORE_BUSY` and raise :class:`StoreBusy`."""


def publish(app: FastAPI, port: int) -> Path | None:
    """Called once the server listens on ``port``: write the endpoint file when this process
    owns the queue. Returns its path, or ``None`` when nothing was written."""
    return None


def withdraw(app: FastAPI) -> None:
    """Called by the lifespan at close, before the queue frees its lock: remove the endpoint
    file that this run wrote."""
