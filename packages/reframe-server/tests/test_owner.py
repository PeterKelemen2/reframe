"""``server.json`` and the life of the server that owns the queue, with the real
``reframe-server`` process where the process matters."""

from __future__ import annotations

import json
import logging
import os
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from websockets.sync.client import connect

from reframe import settings as settings_module
from reframe.models import ServerEndpoint
from reframe.queue.lock import LOCK_FILE, StoreLock
from reframe_server import owner
from reframe_testing import fake_tools as ft
from reframe_testing.server import PROBE_RULE, ApiFactory

pytestmark = pytest.mark.anyio

IDLE_EXIT = 1.0

HANG = ft.Scenario(
    [
        PROBE_RULE,
        ft.Rule(
            tool="ffmpeg",
            argv_has=["matroska"],
            actions=[ft.progress(blocks=1, end=False), ft.hang()],
        ),
    ]
)
"""Each encode prints one progress block, then runs until it is stopped."""


@dataclass
class Home:
    """The folders and environment of a real server process."""

    path: Path
    env: dict[str, str]

    @property
    def data(self) -> Path:
        return self.path / "data"

    @property
    def endpoint(self) -> Path:
        return self.data / owner.ENDPOINT_FILE

    @property
    def log(self) -> Path:
        return self.path / "server.log"


@pytest.fixture
def home(tmp_path: Path, fake_tools: ft.FakeTools) -> Home:
    """No token is given: the server's token is random, so only ``server.json`` can tell it."""
    path = tmp_path / "home"
    env = {name: value for name, value in os.environ.items() if not name.startswith("REFRAME_")}
    for name in ("config", "data", "cache"):
        env[f"REFRAME_{name.upper()}_DIR"] = str(path / name)
    (path / "config").mkdir(parents=True)
    (path / "config" / "settings.json").write_text(
        json.dumps({"encoders": {"hardware_tests": False}, "queue": {"sleep_inhibit": False}}),
        encoding="utf-8",
    )
    env["REFRAME_FFMPEG"] = str(fake_tools.ffmpeg)
    env["REFRAME_FFPROBE"] = str(fake_tools.ffprobe)
    return Home(path, env)


@contextmanager
def running_server(home: Home, *args: str) -> Iterator[subprocess.Popen[bytes]]:
    argv = [sys.executable, "-m", "reframe_server", "--port", "0", *args]
    with home.log.open("ab") as log:
        server = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=log, env=home.env)
    try:
        yield server
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()


def wait_for_endpoint(
    home: Home, server: subprocess.Popen[bytes], *, replacing: str | None = None
) -> ServerEndpoint:
    """The endpoint file as soon as it exists (and names another run than ``replacing``)."""
    deadline = time.monotonic() + 60
    while True:
        try:
            endpoint = ServerEndpoint.model_validate_json(home.endpoint.read_bytes())
        except FileNotFoundError:
            pass
        else:
            if endpoint.instance != replacing:
                return endpoint
        assert server.poll() is None, f"the server exited with {server.returncode}"
        assert time.monotonic() < deadline, "no endpoint file in time"
        time.sleep(0.01)


def wait_until(check: Callable[[], Any], limit: float = 30.0) -> Any:
    deadline = time.monotonic() + limit
    while not (result := check()):
        assert time.monotonic() < deadline, "not in time"
        time.sleep(0.02)
    return result


def start_hanging_job(client: httpx.Client, source: Path, output: Path) -> str:
    """Add a job for ``source`` the way a client does, start it, and return its id once its
    encode runs."""
    accepted = client.post("/api/sources", json={"paths": [str(source)]}).json()

    def probed() -> Any:
        task = client.get(f"/api/tasks/{accepted['task_id']}").json()
        return task["result"] if task["state"] == "done" else None

    source_id = wait_until(probed)["sources"][0]["id"]
    job = client.post("/api/jobs/draft", json={"source_id": source_id}).json()["job"]
    job["output"]["path"] = str(output)
    [added] = client.post("/api/queue", json={"jobs": [job]}).json()
    assert client.post("/api/queue/start").status_code == 204
    wait_until(lambda: client.get("/api/queue").json()["jobs"][0]["state"] == "running")
    job_id: str = added["id"]
    return job_id


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Popen.send_signal cannot send SIGINT on Windows, and Windows has no file modes",
)
def test_the_endpoint_file_names_the_listening_server_until_it_stops(home: Home) -> None:
    """Password mode with no password set: only the file's token gets a client in."""
    with running_server(home, "--auth", "password") as server:
        endpoint = wait_for_endpoint(home, server)
        url = f"http://127.0.0.1:{endpoint.port}"
        health = httpx.get(f"{url}/api/health", timeout=10)  # no retry: it listened first
        assert health.json()["instance"] == endpoint.instance
        assert health.json()["api_version"] == endpoint.api_version
        assert endpoint.token not in health.text
        assert endpoint.pid == server.pid
        assert stat.S_IMODE(home.endpoint.stat().st_mode) == 0o600
        bearer = {"Authorization": f"Bearer {endpoint.token}"}
        assert httpx.get(f"{url}/api/queue", headers=bearer, timeout=10).status_code == 200
        assert httpx.get(f"{url}/api/queue", timeout=10).status_code == 401
        server.send_signal(signal.SIGINT)
        server.wait(30)
    assert not home.endpoint.exists()
    log = home.log.read_text(errors="replace")
    assert endpoint.token not in log
    assert "Traceback" not in log


def test_a_file_left_by_kill_9_is_replaced_by_the_next_owner(home: Home) -> None:
    with running_server(home) as first:
        stale = wait_for_endpoint(home, first)
        first.kill()
        first.wait()
    assert ServerEndpoint.model_validate_json(home.endpoint.read_bytes()) == stale
    with running_server(home) as second:
        fresh = wait_for_endpoint(home, second, replacing=stale.instance)
        assert fresh.pid == second.pid
        health = httpx.get(f"http://127.0.0.1:{fresh.port}/api/health", timeout=10)
        assert health.json()["instance"] == fresh.instance


def test_owner_only_exits_75_against_a_held_lock_and_writes_nothing(home: Home) -> None:
    lock = StoreLock(home.data / LOCK_FILE)
    assert lock.acquire().owned
    try:
        with running_server(home, "--mode", "desktop", "--owner-only") as server:
            code = server.wait(60)
    finally:
        lock.release()
    assert not home.endpoint.exists()
    assert code == owner.EXIT_STORE_BUSY


@pytest.mark.slow
def test_idle_exit_waits_for_an_event_connection_and_a_running_job(
    home: Home, fake_tools: ft.FakeTools, tmp_path: Path
) -> None:
    """A server that a CLI started (``--owner-only --idle-exit``) stays while a client is
    connected or a job runs, and exits once it has been idle for the whole time."""
    fake_tools.set_scenario(HANG)
    source = tmp_path / "Show.mkv"
    source.write_bytes(b"not really matroska")
    argv = ("--mode", "desktop", "--owner-only", "--idle-exit", str(IDLE_EXIT))
    with running_server(home, *argv) as server:
        endpoint = wait_for_endpoint(home, server)
        base_url = f"http://127.0.0.1:{endpoint.port}"
        bearer = {"Authorization": f"Bearer {endpoint.token}"}
        with (
            httpx.Client(base_url=base_url, headers=bearer, timeout=10) as client,
            connect(f"ws://127.0.0.1:{endpoint.port}/api/events", open_timeout=10) as events,
        ):
            events.send(json.dumps({"type": "auth", "token": endpoint.token}))
            assert json.loads(events.recv(10))["type"] == "hello"
            time.sleep(2 * IDLE_EXIT)
            assert server.poll() is None, "it exited while a client was connected"
            job_id = start_hanging_job(client, source, tmp_path / "out" / "Show.mkv")
        time.sleep(2 * IDLE_EXIT)
        assert server.poll() is None, "it exited while a job ran"
        with httpx.Client(base_url=base_url, headers=bearer, timeout=10) as client:
            assert client.post(f"/api/queue/{job_id}/cancel").status_code == 204
        idle_from = time.monotonic()
        code = server.wait(IDLE_EXIT + 30)
        idle_for = time.monotonic() - idle_from
    assert code == 0
    assert idle_for >= IDLE_EXIT


def owners_file(path: Path, instance: str) -> bytes:
    endpoint = ServerEndpoint(
        pid=os.getpid(),
        instance=instance,
        port=8123,
        token="the-owners-token",
        version="0.0.0",
        api_version=1,
        started_at=datetime.now(UTC),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(endpoint.model_dump_json(), encoding="utf-8")
    return path.read_bytes()


async def test_a_server_that_does_not_own_the_queue_leaves_the_owners_file_alone(
    make_api: ApiFactory, tmp_path: Path
) -> None:
    """Another process holds the lock: this server neither replaces its file nor removes it
    at close."""
    lock = StoreLock(tmp_path / "data" / LOCK_FILE)
    assert lock.acquire().owned
    endpoint = tmp_path / "data" / owner.ENDPOINT_FILE
    written = owners_file(endpoint, "the-owner")
    try:
        async with make_api() as api:
            assert owner.publish(api.app, 8000) is None
    finally:
        lock.release()
    assert endpoint.read_bytes() == written


async def test_an_endpoint_file_that_cannot_be_written_is_logged_and_the_server_runs_on(
    make_api: ApiFactory, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("", encoding="utf-8")
    async with make_api(endpoint_file=blocker / owner.ENDPOINT_FILE) as api:
        with caplog.at_level(logging.WARNING, logger=owner.__name__):
            assert owner.publish(api.app, 8000) is None
    assert str(blocker) in caplog.text
    assert api.token not in caplog.text


async def test_a_file_that_cannot_be_removed_at_close_does_not_stop_the_close(
    make_api: ApiFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows refuses to remove a file that a client has open: the queue still closes and
    frees its lock (the file stays, as after ``kill -9``)."""
    endpoint = tmp_path / "data" / owner.ENDPOINT_FILE
    unlink = Path.unlink

    def in_use(path: Path, missing_ok: bool = False) -> None:
        if path == endpoint:
            raise PermissionError(13, "The file is in use by another process", str(path))
        unlink(path, missing_ok)

    async with make_api() as api:
        assert owner.publish(api.app, 8000) == endpoint
        monkeypatch.setattr(Path, "unlink", in_use)
    assert endpoint.exists()
    lock = StoreLock(tmp_path / "data" / LOCK_FILE)
    assert lock.acquire().owned
    lock.release()


async def test_on_windows_publish_waits_for_a_client_that_has_the_file_open(
    make_api: ApiFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client reads a stale file just as the next owner replaces it: Windows refuses the
    replace for a moment."""
    endpoint = tmp_path / "data" / owner.ENDPOINT_FILE
    owners_file(endpoint, "a-killed-owner")
    replace = os.replace
    refused: list[Path] = []

    def open_elsewhere(source: Any, target: Any) -> None:
        if Path(target) == endpoint and not refused:
            refused.append(endpoint)
            raise PermissionError(13, "Access is denied", str(target))
        replace(source, target)

    monkeypatch.setattr(settings_module, "WINDOWS", True)
    monkeypatch.setattr(os, "replace", open_elsewhere)
    async with make_api() as api:
        assert owner.publish(api.app, 8000) == endpoint
        written = ServerEndpoint.model_validate_json(endpoint.read_bytes())
        assert written.instance == api.app.state.instance
    assert refused == [endpoint]
