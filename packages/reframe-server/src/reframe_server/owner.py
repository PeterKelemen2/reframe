"""The server that owns the queue: it opens the queue at start-up, publishes ``server.json``
once it listens, and removes it at close. With ``owner_only`` a server that cannot own the
queue does not start. The file holds the run's token, so it is never logged."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI

from reframe.models import ServerEndpoint
from reframe.service import Reframe
from reframe.settings import JsonDocumentFile
from reframe_server import __version__
from reframe_server.api import API_VERSION
from reframe_server.config import ServerConfig

__all__ = [
    "ENDPOINT_FILE",
    "EXIT_STORE_BUSY",
    "ServerEndpoint",
    "StoreBusy",
    "publish",
    "start",
    "withdraw",
]

log = logging.getLogger(__name__)

ENDPOINT_FILE = "server.json"
EXIT_STORE_BUSY = 75
"""The exit code of ``--owner-only`` when another process owns the queue (``EX_TEMPFAIL``)."""


class StoreBusy(Exception):
    """``owner_only``, and another process owns the queue: the server does not start."""


def _endpoint_path(app: FastAPI) -> Path:
    config: ServerConfig = app.state.config
    reframe: Reframe = app.state.reframe
    return config.endpoint_file or reframe.data_dir / ENDPOINT_FILE


def start(app: FastAPI) -> None:
    """Called by the lifespan once the facade exists (``app.state.reframe``): open the queue.
    When another process owns it and ``config.owner_only`` is set, set ``app.state.exit_code``
    to :data:`EXIT_STORE_BUSY` and raise :class:`StoreBusy`. Blocking, briefly: the lock is
    taken without waiting."""
    reframe: Reframe = app.state.reframe
    config: ServerConfig = app.state.config
    reframe.queue.list()
    if reframe.queue.owns_store:
        return
    if config.owner_only:
        app.state.exit_code = EXIT_STORE_BUSY
        raise StoreBusy(f"another Reframe process owns the queue of {reframe.data_dir}")
    log.warning(
        "another Reframe process owns the queue of %s (or its lock cannot be used): the jobs "
        "of this server are not saved, and it writes no %s",
        reframe.data_dir,
        ENDPOINT_FILE,
    )


def publish(app: FastAPI, port: int) -> Path | None:
    """Called once the server listens on ``port``: write the endpoint file when this process
    owns the queue (atomic, mode 0600 on POSIX from its creation, over a stale file). Returns
    its path, or ``None`` when nothing was written. Never raises for a file that cannot be
    written: the server runs on, and clients do not find it."""
    reframe: Reframe = app.state.reframe
    config: ServerConfig = app.state.config
    if not reframe.queue.owns_store:
        return None
    path = _endpoint_path(app)
    endpoint = ServerEndpoint(
        pid=os.getpid(),
        instance=app.state.instance,
        port=port,
        token=config.secret_token,
        version=__version__,
        api_version=API_VERSION,
        started_at=datetime.now(UTC),
    )
    problem = JsonDocumentFile(path).write(endpoint.model_dump(mode="json"))
    if problem is not None:
        log.warning("other Reframe programs cannot find this server: %s", problem)
        return None
    return path


def withdraw(app: FastAPI) -> None:
    """Called by the lifespan at close, before the queue frees its lock: remove the endpoint
    file if it names this run. Never raises: the lifespan must go on to close the queue."""
    path = _endpoint_path(app)
    read = JsonDocumentFile(path).read()
    if read.data is None or read.data.get("instance") != app.state.instance:
        return
    try:
        path.unlink()
    except OSError as exc:  # Windows: a client has it open; a stale file is only a hint
        log.warning("%s cannot be removed: %s", path, exc)
