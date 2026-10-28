"""Finding the server that owns the queue of a data folder: the one that ``server.json`` names
and that answers with the same ``instance`` and ``api_version``; else one started for this
client; else the reason why there is none. The file is only a hint: what holds ``queue.lock``
is the owner."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from reframe.models.queue import ServerEndpoint
from reframe.platform.childproc import CREATE_NO_WINDOW, launch_detached
from reframe.queue.lock import LOCK_FILE, StoreLock

__all__ = [
    "API_VERSION",
    "ENDPOINT_ENV",
    "ENDPOINT_FILE",
    "EXIT_STORE_BUSY",
    "HELD_WAIT",
    "IDLE_EXIT",
    "START_LOCK",
    "START_WAIT",
    "NoOwner",
    "Owner",
    "OwnerSearch",
    "endpoint_path",
    "find_owner",
    "owner_command",
    "read_endpoint",
]

log = logging.getLogger(__name__)

API_VERSION = 1
"""The server API this client speaks (``GET /api/health``'s ``api_version``)."""
ENDPOINT_FILE = "server.json"
ENDPOINT_ENV = "REFRAME_ENDPOINT_FILE"
"""Where the server writes the endpoint file instead of ``<data dir>/server.json``."""
START_LOCK = "server-start.lock"
"""Held by the client that starts an owner, so that clients that start at once start one."""
START_WAIT = 10.0
"""Seconds to wait for an owner that this client started."""
HELD_WAIT = 5.0
"""Seconds to wait while another process holds ``queue.lock`` and no endpoint answers: an
owner that is starting, or one in its exit window (port closed, lock not yet free)."""
IDLE_EXIT = 30
"""Seconds a started owner stays without a running job or a connected client."""
EXIT_STORE_BUSY = 75
"""``--owner-only``'s exit code when another process holds the lock."""
HEALTH_TIMEOUT = 2.0
POLL = 0.05


@dataclass(frozen=True)
class Owner:
    """A server that owns the queue and speaks this client's API."""

    endpoint: ServerEndpoint
    version: str
    started: bool = False
    """This client started it."""

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.endpoint.port}"


@dataclass(frozen=True)
class NoOwner:
    """No server can be used; ``reason`` says why, for the user."""

    reason: str


def endpoint_path(data_dir: Path, environ: Mapping[str, str] | None = None) -> Path:
    """The endpoint file the server of ``data_dir`` writes (the same rule as the server)."""
    value = (os.environ if environ is None else environ).get(ENDPOINT_ENV, "").strip()
    return Path(value) if value else data_dir / ENDPOINT_FILE


def read_endpoint(path: Path) -> ServerEndpoint | None:
    """The endpoint file, or ``None`` when it is missing or not valid. Never raises, never logs
    the token."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        return ServerEndpoint.model_validate(json.loads(raw))
    except ValidationError as exc:
        log.debug("%s is not valid: %s", path, exc.errors(include_input=False))
    except (ValueError, RecursionError):
        log.debug("%s is not JSON", path)
    return None


def owner_command(
    *,
    executable: str | None = None,
    frozen: bool | None = None,
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
) -> list[str] | None:
    """The command that starts an owner with this client's version: the server package of
    this environment, or the frozen server next to a frozen CLI; ``None`` when there is none."""
    executable = sys.executable if executable is None else executable
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    options = [
        "--mode",
        "desktop",
        "--host",
        "127.0.0.1",
        "--port",
        "0",
        "--owner-only",
        "--idle-exit",
        str(IDLE_EXIT),
    ]
    if frozen:
        here = Path(executable).parent
        for name in ("reframe-server.exe", "reframe-server"):
            if (here / name).is_file():
                return [str(here / name), *options]
        return None
    if find_spec("reframe_server") is None:
        return None
    return [executable, "-m", "reframe_server", *options]


class Started(Protocol):
    """A started owner: its exit code once it has exited, else ``None``."""

    @property
    def returncode(self) -> int | None: ...


Launch = Callable[[Sequence[str], Path, str], Started]
"""Starts the owner command in the data folder on a platform (``sys.platform``)."""


def _start(
    argv: Sequence[str],
    data_dir: Path,
    platform: str,
    *,
    launcher: Callable[..., int] = launch_detached,
) -> subprocess.Popen[bytes]:
    """Start ``argv`` detached from this process (it must outlive the command); the handle is
    only read for the exit code, which ``launch_detached``'s reaper thread sets."""
    started: list[subprocess.Popen[bytes]] = []

    def popen(args: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
        if platform == "win32":
            # Not tied to the terminal's console: closing it must not end the owner.
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
        process = subprocess.Popen(args, **kwargs)
        started.append(process)
        return process

    launcher(list(argv), cwd=str(data_dir), platform=platform, popen=popen)
    return started[-1]


class OwnerSearch:
    """One search for the owner of ``data_dir`` (see :func:`find_owner`)."""

    def __init__(
        self,
        data_dir: Path,
        *,
        start: bool,
        command: Sequence[str] | None,
        launch: Launch,
        platform: str,
        environ: Mapping[str, str] | None,
    ) -> None:
        self.data_dir = data_dir
        self.start = start
        self.command = command
        self.launch = launch
        self.platform = platform
        self.endpoint_file = endpoint_path(data_dir, environ)
        self.launched: Started | None = None
        self._start_lock = StoreLock(data_dir / START_LOCK)

    async def run(self) -> Owner | NoOwner:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + START_WAIT + HELD_WAIT
        held_since: float | None = None
        launched_at = 0.0
        async with httpx.AsyncClient(timeout=HEALTH_TIMEOUT) as client:
            try:
                while True:
                    found = await self._endpoint(client)
                    if found is not None:
                        return found
                    now = loop.time()
                    if self.launched is not None:
                        code = self.launched.returncode
                        if code is None:
                            if now - launched_at > START_WAIT:
                                return NoOwner(
                                    f"the Reframe server started for this command did not "
                                    f"answer within {START_WAIT:g} s"
                                )
                            await asyncio.sleep(POLL)
                            continue
                        self.launched = None
                        if code != EXIT_STORE_BUSY:
                            return NoOwner(
                                f"the Reframe server started for this command exited with code "
                                f"{code}"
                            )
                        # Another process took the lock first: its endpoint comes, or it is
                        # an owner without one.
                    if not self.start:
                        return NoOwner("no Reframe server answers for this data folder")
                    if not self._start_lock.held:
                        try:
                            mine = self._start_lock.acquire().owned
                        except OSError as exc:
                            return NoOwner(f"the data folder cannot be used: {exc}")
                        if not mine:  # another client is starting the owner
                            if now > deadline:
                                return NoOwner(
                                    "another Reframe program is starting the server, and it did "
                                    "not answer in time"
                                )
                            await asyncio.sleep(POLL)
                            continue
                    holder = self._lock_holder()
                    if isinstance(holder, NoOwner):
                        return holder
                    if holder is None:
                        held_since = None
                        if now > deadline:
                            return NoOwner("no Reframe server answered in time")
                        if self.command is None:
                            return NoOwner(
                                "the reframe-server package is not installed with this reframe"
                            )
                        try:
                            self.launched = self.launch(self.command, self.data_dir, self.platform)
                        except OSError as exc:
                            return NoOwner(f"the Reframe server cannot be started: {exc}")
                        launched_at = loop.time()
                        continue
                    held_since = now if held_since is None else held_since
                    if now - held_since > HELD_WAIT:
                        who = f" (pid {holder})" if holder > 0 else ""
                        return NoOwner(
                            f"another Reframe process{who} owns the queue and is not a server "
                            "this command can use"
                        )
                    await asyncio.sleep(POLL)
            finally:
                self._start_lock.release()

    async def _endpoint(self, client: httpx.AsyncClient) -> Owner | NoOwner | None:
        """The owner that the endpoint file names, a refusal for another API version, or
        ``None`` when the file is missing, stale or its server does not answer."""
        endpoint = await asyncio.to_thread(read_endpoint, self.endpoint_file)
        if endpoint is None:
            return None
        try:
            response = await client.get(f"http://127.0.0.1:{endpoint.port}/api/health")
            health = response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(health, dict) or health.get("instance") != endpoint.instance:
            return None  # another program on that port, or another run: the file is stale
        version = str(health.get("version", endpoint.version))
        if health.get("api_version") != API_VERSION:
            return NoOwner(
                f"Reframe {version} (pid {endpoint.pid}) owns the queue, and it speaks API "
                f"version {health.get('api_version')}, not {API_VERSION} as this reframe does"
            )
        return Owner(endpoint, version, started=self.launched is not None)

    def _lock_holder(self) -> int | NoOwner | None:
        """``None`` when ``queue.lock`` is free; else the holder's pid (0: unknown)."""
        lock = StoreLock(self.data_dir / LOCK_FILE)
        try:
            result = lock.acquire()
        except OSError as exc:
            return NoOwner(f"the saved queue cannot be used: {exc}")
        if result.owned:
            lock.release()
            return None
        return result.owner or 0


async def find_owner(
    data_dir: Path,
    *,
    start: bool = True,
    command: Callable[[], Sequence[str] | None] | None = None,
    launch: Launch | None = None,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Owner | NoOwner:
    """The owner of ``data_dir``'s queue: the server that ``server.json`` names, if it answers
    with its ``instance`` and this client's ``api_version``. Else, with ``start``, a server
    started with ``command()`` (default :func:`owner_command`) while ``queue.lock`` is free; its
    exit code 75 means another owner won. Waits at most :data:`START_WAIT` for a started owner
    and :data:`HELD_WAIT` while another process holds the lock without an endpoint. Without
    ``start`` neither ``queue.lock`` nor anything else is touched. Never raises."""
    search = OwnerSearch(
        data_dir,
        start=start,
        command=(owner_command if command is None else command)(),
        launch=_start if launch is None else launch,
        platform=sys.platform if platform is None else platform,
        environ=environ,
    )
    return await search.run()
