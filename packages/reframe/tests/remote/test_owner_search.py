"""Finding the owner of a data folder: the server that ``server.json`` names, else one started
for the client, else the reason. The owner is the test's own server in this event loop; a
started owner is a fake process."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import socket
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from reframe.platform.childproc import CREATE_NO_WINDOW, launch_detached
from reframe.queue.lock import LOCK_FILE, StoreLock
from reframe.remote import API_VERSION, NoOwner, Owner, find_owner
from reframe.remote import owner as owner_module
from reframe.remote.owner import (
    ENDPOINT_ENV,
    ENDPOINT_FILE,
    SERVER_OPTIONS,
    START_LOCK,
    endpoint_path,
    owner_command,
    owner_environment,
    read_endpoint,
    server_log,
)

from .conftest import Server

pytestmark = pytest.mark.anyio

COMMAND = ["reframe-server", "--owner-only"]


class FakeStart:
    """Stands in for the started owner: ``on_start`` plays what the server does."""

    def __init__(self, on_start: Callable[[FakeStart], None] | None = None) -> None:
        self.on_start = on_start
        self.started: list[tuple[list[str], Path, str]] = []
        self.returncode: int | None = None

    def __call__(self, argv: Sequence[str], data_dir: Path, platform: str) -> FakeStart:
        self.started.append((list(argv), data_dir, platform))
        if self.on_start is not None:
            self.on_start(self)
        return self


def later(seconds: float, action: Callable[[], object]) -> None:
    asyncio.get_running_loop().call_later(seconds, action)


async def search(server: Server, launch: FakeStart, **options: Any) -> Owner | NoOwner:
    return await find_owner(
        server.data_dir, command=lambda: COMMAND, launch=launch, platform="linux", **options
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def write_endpoint(server: Server, **fields: Any) -> None:
    data = json.loads(server.owner().endpoint.model_dump_json())
    data.update(fields)
    (server.data_dir / ENDPOINT_FILE).write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
async def unowned(server: Server) -> Server:
    """The test's server answers its health route, but ``queue.lock`` is free."""
    await server.api.reframe.queue.close()
    return server


@pytest.fixture
def short_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(owner_module, "START_WAIT", 0.4)
    monkeypatch.setattr(owner_module, "HELD_WAIT", 0.4)


async def test_the_server_that_the_endpoint_file_names_is_used(server: Server) -> None:
    server.publish()
    start = FakeStart()
    found = await search(server, start)
    assert isinstance(found, Owner)
    assert found.endpoint.port == server.live.port
    assert start.started == []


async def test_a_server_of_another_api_version_is_not_used_and_the_reason_names_it(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reframe_server.routers import health

    monkeypatch.setattr(health, "API_VERSION", 2)
    server.publish()
    start = FakeStart()
    found = await search(server, start)
    assert isinstance(found, NoOwner)
    assert f"(pid {os.getpid()}) owns the queue" in found.reason
    assert "API version 2, not 1" in found.reason
    assert start.started == []


async def test_a_stale_file_and_a_free_lock_start_an_owner(unowned: Server) -> None:
    write_endpoint(unowned, port=free_port())
    start = FakeStart(lambda _: later(0.2, unowned.publish))
    found = await search(unowned, start)
    assert isinstance(found, Owner)
    assert start.started == [(COMMAND, unowned.data_dir, "linux")]


async def test_a_file_of_another_run_on_the_port_is_stale(unowned: Server) -> None:
    write_endpoint(unowned, instance="an-earlier-run")
    start = FakeStart(lambda _: later(0.1, unowned.publish))
    found = await search(unowned, start)
    assert isinstance(found, Owner)
    assert len(start.started) == 1


async def test_a_started_owner_that_exits_gives_its_exit_code(unowned: Server) -> None:
    def fails(start: FakeStart) -> None:
        start.returncode = 1

    found = await search(unowned, FakeStart(fails))
    assert found == NoOwner("the Reframe server started for this command exited with code 1")


async def test_exit_75_means_another_owner_won_and_its_endpoint_is_used(unowned: Server) -> None:
    winner = StoreLock(unowned.data_dir / LOCK_FILE)

    def loses(start: FakeStart) -> None:
        assert winner.acquire().owned
        start.returncode = 75
        later(0.2, unowned.publish)

    try:
        found = await search(unowned, FakeStart(loses))
    finally:
        winner.release()
    assert isinstance(found, Owner)


async def test_a_started_owner_that_does_not_answer_in_time(
    unowned: Server, short_waits: None
) -> None:
    found = await search(unowned, FakeStart())
    assert isinstance(found, NoOwner)
    assert "did not answer within 0.4 s" in found.reason


async def test_a_held_lock_without_an_endpoint_is_an_owner_this_client_cannot_use(
    unowned: Server, short_waits: None
) -> None:
    holder = StoreLock(unowned.data_dir / LOCK_FILE)
    assert holder.acquire().owned
    start = FakeStart()
    try:
        found = await search(unowned, start)
    finally:
        holder.release()
    assert isinstance(found, NoOwner)
    assert f"another Reframe process (pid {os.getpid()}) owns the queue" in found.reason
    assert start.started == []


async def test_an_owner_that_holds_the_lock_before_it_publishes_is_waited_for(
    unowned: Server,
) -> None:
    """A server that is starting, or one in its exit window, holds the lock without an
    endpoint that answers."""
    holder = StoreLock(unowned.data_dir / LOCK_FILE)
    assert holder.acquire().owned
    later(0.3, unowned.publish)
    start = FakeStart()
    try:
        found = await search(unowned, start)
    finally:
        holder.release()
    assert isinstance(found, Owner)
    assert start.started == []


async def test_without_start_nothing_is_started_or_locked(server: Server) -> None:
    start = FakeStart()
    found = await search(server, start, start=False)
    assert found == NoOwner("no Reframe server answers for this data folder")
    assert start.started == []
    assert not (server.data_dir / START_LOCK).exists()


async def test_without_the_server_package_no_owner_is_started(unowned: Server) -> None:
    found = await find_owner(unowned.data_dir, command=lambda: None, launch=FakeStart())
    assert found == NoOwner("the reframe-server package is not installed with this reframe")


async def test_clients_that_search_at_once_start_one_owner(unowned: Server) -> None:
    start = FakeStart(lambda _: later(0.3, unowned.publish))
    found = await asyncio.gather(*(search(unowned, start) for _ in range(3)))
    assert all(isinstance(each, Owner) for each in found)
    assert len(start.started) == 1


async def test_a_client_that_starts_an_owner_is_waited_for_until_the_time_is_up(
    server: Server, short_waits: None
) -> None:
    other_client = StoreLock(server.data_dir / START_LOCK)
    assert other_client.acquire().owned
    start = FakeStart()
    try:
        found = await search(server, start)
    finally:
        other_client.release()
    assert isinstance(found, NoOwner)
    assert "another Reframe program is starting the server" in found.reason
    assert start.started == []


async def test_a_queue_lock_that_cannot_be_used(server: Server) -> None:
    lock = server.data_dir / LOCK_FILE
    await server.api.reframe.queue.close()
    lock.unlink()
    lock.mkdir()
    found = await search(server, FakeStart())
    assert isinstance(found, NoOwner)
    assert found.reason.startswith("the saved queue cannot be used:")


def test_the_owner_command() -> None:
    options = ["--mode", "desktop", "--host", "127.0.0.1", "--port", "0", "--owner-only"]
    command = owner_command(
        executable="/env/bin/python", frozen=False, find_spec=lambda _: object()
    )
    assert command == ["/env/bin/python", "-m", "reframe_server", *options, "--idle-exit", "30"]
    assert (
        owner_command(executable="/env/bin/python", frozen=False, find_spec=lambda _: None) is None
    )


def test_a_frozen_cli_starts_the_frozen_server_next_to_it(tmp_path: Path) -> None:
    cli = tmp_path / "reframe"
    assert owner_command(executable=str(cli), frozen=True) is None
    (tmp_path / "reframe-server").write_bytes(b"")
    command = owner_command(executable=str(cli), frozen=True)
    assert command is not None
    assert command[0] == str(tmp_path / "reframe-server")
    assert "--owner-only" in command


@pytest.mark.parametrize(
    ("platform", "breakaway"),
    [("linux", True), ("win32", True), ("win32", False)],
    ids=["linux", "win32", "win32 in a job without breakaway"],
)
def test_a_started_owner_is_detached_from_the_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, breakaway: bool
) -> None:
    """On Windows it also has no console: closing the terminal must not end it, also when it
    has to start inside the terminal's job."""
    created: list[dict[str, Any]] = []
    refusals = [] if breakaway else [PermissionError(5, "Access is denied")]

    class Process:
        pid = 4242
        returncode = None

        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            if refusals:
                raise refusals.pop()
            created.append({"argv": argv, **kwargs})

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", Process)
    owner_module._start(
        ["reframe-server"],
        tmp_path,
        platform,
        launcher=lambda *args, **kwargs: launch_detached(*args, **kwargs),
    )
    [options] = created
    assert options["cwd"] == str(tmp_path)
    if platform == "win32":
        assert options["creationflags"] & CREATE_NO_WINDOW
    else:
        assert options["start_new_session"] is True
        assert "creationflags" not in options


@pytest.mark.parametrize(
    "text",
    [json.dumps({"token": "the-secret-token", "port": "x"}), '{"token": "the-secret-token", '],
    ids=["not valid", "not JSON"],
)
def test_an_endpoint_file_that_is_not_valid_is_ignored_without_logging_its_token(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, text: str
) -> None:
    path = tmp_path / ENDPOINT_FILE
    path.write_text(text, encoding="utf-8")
    with caplog.at_level(logging.DEBUG, logger=owner_module.__name__):
        assert read_endpoint(path) is None
    assert caplog.records
    assert "the-secret-token" not in caplog.text


async def test_an_owner_that_cannot_be_started(unowned: Server) -> None:
    def fails(_start: FakeStart) -> None:
        raise FileNotFoundError(2, "No such file or directory", "reframe-server")

    found = await search(unowned, FakeStart(fails))
    assert isinstance(found, NoOwner)
    assert found.reason.startswith("the Reframe server cannot be started: ")


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="POSIX folder modes, not as root"
)
async def test_a_data_folder_that_cannot_be_written(unowned: Server) -> None:
    unowned.data_dir.chmod(0o555)
    try:
        found = await search(unowned, FakeStart())
    finally:
        unowned.data_dir.chmod(0o755)
    assert isinstance(found, NoOwner)
    assert found.reason.startswith("the data folder cannot be used: ")


def test_the_endpoint_file_follows_the_servers_setting(tmp_path: Path) -> None:
    """The server's own test reads the same values: a client that looks elsewhere waits for a
    file that its owner never writes, and the owner keeps the lock."""
    assert endpoint_path(tmp_path, {}) == tmp_path / ENDPOINT_FILE
    assert endpoint_path(tmp_path, {ENDPOINT_ENV: "  "}) == tmp_path / ENDPOINT_FILE
    elsewhere = tmp_path / "elsewhere.json"
    assert endpoint_path(tmp_path, {ENDPOINT_ENV: f" {elsewhere} "}) == elsewhere


def test_the_client_speaks_the_api_version_of_the_server_of_its_own_version() -> None:
    from reframe_server.api import API_VERSION as SERVER_API

    assert API_VERSION == SERVER_API


async def test_the_health_check_does_not_send_the_token(server: Server) -> None:
    """``server.json`` may be stale and its port another program's: that program must not
    get the token."""
    requests: list[bytes] = []

    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        requests.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 404 Not Found\r\ncontent-length: 0\r\n\r\n")
        await writer.drain()
        writer.close()

    other_program = await asyncio.start_server(answer, "127.0.0.1", 0)
    async with other_program:
        write_endpoint(server, port=other_program.sockets[0].getsockname()[1])
        found = await search(server, FakeStart(), start=False)
    assert found == NoOwner("no Reframe server answers for this data folder")
    [request] = requests
    assert server.api.token.encode() not in request


async def test_a_search_frees_the_start_lock(unowned: Server) -> None:
    """Held on, it makes every later client wait for an owner that this one started."""
    found = await search(unowned, FakeStart(lambda _: later(0.1, unowned.publish)))
    assert isinstance(found, Owner)
    other_client = StoreLock(unowned.data_dir / START_LOCK)
    assert other_client.acquire().owned
    other_client.release()


async def test_an_owner_whose_token_cannot_be_sent_is_not_used(server: Server) -> None:
    """``REFRAME_TOKEN`` with a space at its end: every request fails with a message that
    shows the token."""
    write_endpoint(server, token="SECRET-TOKEN-xyz ")
    found = await search(server, FakeStart(), start=False)
    assert isinstance(found, NoOwner)
    assert "cannot be sent in an HTTP header" in found.reason
    assert "SECRET" not in found.reason


def detached(*args: Any, **kwargs: Any) -> int:
    """``launch_detached`` itself: the test guard refuses only the default launcher."""
    return launch_detached(*args, **kwargs)


@pytest.mark.parametrize("log_before", ["", "an earlier run's long log\n"], ids=["new", "full"])
async def test_a_started_owner_that_fails_points_to_its_messages(
    unowned: Server, monkeypatch: pytest.MonkeyPatch, log_before: str
) -> None:
    """The client points to the messages that say why its owner failed. ``REFRAME_AUTH`` of
    the shell, which made a started owner exit 2, does not reach the owner. A log that grew
    past its limit is emptied first, or the data folder fills up over the months."""
    monkeypatch.setenv("REFRAME_AUTH", "password")
    monkeypatch.setattr(owner_module, "SERVER_LOG_LIMIT", 10)
    log = server_log(unowned.data_dir)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(log_before, encoding="utf-8")
    script = (
        "import os, sys; "
        "sys.stderr.write(f'auth: {os.environ.get(\"REFRAME_AUTH\")}\\n'); "
        "sys.exit(2)"
    )
    found = await find_owner(
        unowned.data_dir,
        command=lambda: [sys.executable, "-c", script],
        launch=functools.partial(owner_module._start, launcher=detached),
    )
    assert found == NoOwner(
        f"the Reframe server started for this command exited with code 2 (see {log})"
    )
    assert log.read_text(encoding="utf-8") == "auth: None\n"


def test_a_log_that_cannot_be_opened_does_not_stop_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "logs").write_text("a file where the folder should be", encoding="utf-8")
    created: list[dict[str, Any]] = []

    class Process:
        pid = 4242
        returncode = None

        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            created.append(kwargs)

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", Process)
    with caplog.at_level(logging.WARNING, logger=owner_module.__name__):
        owner_module._start(["reframe-server"], tmp_path, "linux", launcher=detached)
    [options] = created
    assert options["stderr"] == subprocess.DEVNULL
    assert "the Reframe server's messages cannot be written" in caplog.text


def test_a_started_owner_has_the_clients_folders_as_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It runs in the data folder: a relative ``REFRAME_DATA_DIR`` would name a folder inside it,
    and the client would wait for a ``server.json`` that its owner writes there."""
    monkeypatch.chdir(tmp_path)
    environ = {
        "PATH": "/usr/bin",
        "REFRAME_DATA_DIR": "data",
        "REFRAME_CONFIG_DIR": "config",
        "REFRAME_CACHE_DIR": "cache",
        "REFRAME_ENDPOINT_FILE": "elsewhere.json",
        "REFRAME_FFMPEG": "/opt/ffmpeg/bin/ffmpeg",
        "reframe_token": "SECRET-TOKEN-xyz ",  # the server reads names in any case
    }
    assert owner_environment(Path("data"), environ) == {
        "PATH": "/usr/bin",
        "REFRAME_DATA_DIR": str(tmp_path / "data"),
        "REFRAME_CONFIG_DIR": str(tmp_path / "config"),
        "REFRAME_CACHE_DIR": str(tmp_path / "cache"),
        "REFRAME_ENDPOINT_FILE": str(tmp_path / "elsewhere.json"),
        "REFRAME_FFMPEG": "/opt/ffmpeg/bin/ffmpeg",
    }


def test_a_started_owner_leaves_out_every_option_of_the_server() -> None:
    """A server option added later would reach the owners that clients start."""
    from reframe_server.config import ServerConfig

    kept = {"CONFIG_DIR", "DATA_DIR", "ENDPOINT_FILE"}
    assert {name.upper() for name in ServerConfig.model_fields} - kept == SERVER_OPTIONS
