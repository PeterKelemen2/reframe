"""``--parent-pid``: the server stops when the process that started it ends, never takes a
younger process for that parent, and exits hard when its stop does not end in time."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import psutil
import pytest

from reframe_server import parent
from reframe_server.__main__ import serve
from reframe_server.config import ServerConfig
from reframe_testing import media

pytestmark = pytest.mark.anyio

TOKEN = "parent-test-" + "x" * 32


def stand_in() -> subprocess.Popen[bytes]:
    """A process that waits until it is killed: the desktop shell of a test."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])


def ended_pid() -> int:
    """The pid of a process that has ended (and was reaped)."""
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def server_env(home: Path) -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if not name.startswith("REFRAME_")}
    for name in ("config", "data", "cache"):
        env[f"REFRAME_{name.upper()}_DIR"] = str(home / name)
    (home / "config").mkdir(parents=True)
    (home / "config" / "settings.json").write_text(
        json.dumps({"encoders": {"hardware_tests": False}, "queue": {"sleep_inhibit": False}}),
        encoding="utf-8",
    )
    ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
    assert ffmpeg is not None
    assert ffprobe is not None
    return env | {"REFRAME_FFMPEG": ffmpeg, "REFRAME_FFPROBE": ffprobe, "REFRAME_TOKEN": TOKEN}


def ready_port(process: subprocess.Popen[bytes], limit: float = 60.0) -> int:
    lines: queue.Queue[bytes] = queue.Queue()
    stdout = process.stdout
    assert stdout is not None
    threading.Thread(target=lambda: lines.put(stdout.readline()), daemon=True).start()
    port: int = json.loads(lines.get(timeout=limit))["port"]
    return port


def wait_until(check: Callable[[], Any], limit: float = 60.0) -> Any:
    deadline = time.monotonic() + limit
    while not (result := check()):
        assert time.monotonic() < deadline, "not in time"
        time.sleep(0.05)
    return result


def start_encode(client: httpx.Client, source: Path, output: Path) -> dict[str, Any]:
    """An x265 encode of ``source`` that runs for a while; returns the job once it writes."""
    accepted = client.post("/api/sources", json={"paths": [str(source)]}).json()

    def probed() -> Any:
        task = client.get(f"/api/tasks/{accepted['task_id']}").json()
        return task["result"] if task["state"] == "done" else None

    source_id = wait_until(probed)["sources"][0]["id"]
    job = client.post("/api/jobs/draft", json={"source_id": source_id}).json()["job"]
    job["output"]["path"] = str(output)
    job["video"] |= {"encoder": "libx265", "preset": "slow"}
    [added] = client.post("/api/queue", json={"jobs": [job]}).json()
    assert client.post("/api/queue/start").status_code == 204

    def writing() -> Any:
        [queued] = client.get("/api/queue").json()["jobs"]
        assert queued["id"] == added["id"]
        assert queued["state"] in ("waiting", "running"), queued
        progress = queued.get("progress") or {}
        return queued if progress.get("output_size") else None

    job_now: dict[str, Any] = wait_until(writing)
    return job_now


def ffmpeg_processes(pid: int) -> list[psutil.Process]:
    return [p for p in psutil.Process(pid).children(recursive=True) if "ffmpeg" in p.name()]


@pytest.fixture
def shell() -> Iterator[subprocess.Popen[bytes]]:
    process = stand_in()
    yield process
    process.kill()
    process.wait()


@pytest.mark.slow
@pytest.mark.needs_ffmpeg
def test_the_server_and_its_encode_stop_when_the_parent_is_killed(
    tmp_path: Path, fixture_media: Callable[[str], Path], shell: subprocess.Popen[bytes]
) -> None:
    """The desktop shell dies by SIGKILL during an encode: the server stops as a shutdown
    request stops it (before the hard exit), and its FFmpeg and the ``.part`` file go too."""
    source = tmp_path / "media" / "hdr10-4k.mkv"
    source.parent.mkdir()
    shutil.copyfile(fixture_media("hdr10-4k"), source)
    log = tmp_path / "server.log"
    argv = [sys.executable, "-m", "reframe_server", "--mode", "desktop", "--port", "0"]
    with log.open("wb") as stderr:
        server = subprocess.Popen(
            [*argv, "--parent-pid", str(shell.pid)],
            stdout=subprocess.PIPE,
            stderr=stderr,
            env=server_env(tmp_path / "home"),
        )
    try:
        base_url = f"http://127.0.0.1:{ready_port(server)}"
        headers = {"Authorization": f"Bearer {TOKEN}"}
        with httpx.Client(base_url=base_url, headers=headers, timeout=30) as client:
            job = start_encode(client, source, tmp_path / "out" / "encoded.mkv")
        part = Path(job["plan"]["output_tmp"])
        encoders = ffmpeg_processes(server.pid)
        assert encoders
        assert part.exists()
        shell.kill()
        killed = time.monotonic()
        code = server.wait(timeout=parent.STOP_LIMIT + 30)
        took = time.monotonic() - killed
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
        assert server.stdout is not None
        server.stdout.close()
    text = log.read_text(errors="replace")
    assert code == 0, text
    assert took < parent.STOP_LIMIT
    assert f"The parent process {shell.pid} ended" in text
    _, alive = psutil.wait_procs(encoders, timeout=5)
    assert alive == []
    assert not part.exists()


async def test_a_parent_that_is_gone_at_start_stops_the_server_at_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The shell died before its sidecar started: no ready line, the server does not run."""
    gone = ended_pid()
    config = ServerConfig(
        mode="desktop",
        parent_pid=gone,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    assert await asyncio.wait_for(serve(config), 10) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert f"the parent process {gone} is not running" in output.err


async def test_a_process_younger_than_the_server_is_not_its_parent() -> None:
    """The parent ended and the OS gave its pid to a new process before the watch began."""
    younger = stand_in()
    try:
        watch = parent.watch_parent(
            younger.pid, lambda: None, asyncio.get_running_loop(), hard_exit=lambda _code: None
        )
        assert watch is None
    finally:
        younger.kill()
        younger.wait()


async def test_the_server_exits_hard_when_it_has_not_stopped_in_time() -> None:
    ended, released = threading.Event(), threading.Event()
    stopped = asyncio.Event()
    codes: queue.Queue[int] = queue.Queue()
    loop = asyncio.get_running_loop()
    parent.ParentWatch(4242, ended.wait, released.set, stopped.set, loop, 0.3, codes.put)
    began = time.monotonic()
    ended.set()
    await asyncio.wait_for(stopped.wait(), 5)
    code = await asyncio.to_thread(codes.get, timeout=5)
    assert code == parent.HARD_EXIT_CODE
    assert time.monotonic() - began >= 0.3
    assert released.is_set()


async def test_the_parents_end_after_close_changes_nothing() -> None:
    """The server stopped normally and closed its watch; then the shell exits."""
    ended, released = threading.Event(), threading.Event()
    calls: list[object] = []
    loop = asyncio.get_running_loop()
    watch = parent.ParentWatch(
        4242, ended.wait, released.set, lambda: calls.append("stop"), loop, 0.0, calls.append
    )
    watch.close()
    ended.set()
    assert await asyncio.to_thread(released.wait, 5)
    await asyncio.sleep(0.3)
    assert calls == []


def test_the_hard_exit_comes_when_the_event_loop_has_closed() -> None:
    """The parent ends while the server is already past its event loop."""
    loop = asyncio.new_event_loop()
    loop.close()
    ended = threading.Event()
    codes: queue.Queue[int] = queue.Queue()
    parent.ParentWatch(4242, ended.wait, lambda: None, lambda: None, loop, 0.0, codes.put)
    ended.set()
    assert codes.get(timeout=5) == parent.HARD_EXIT_CODE


class FakeKernel32:
    """The Windows calls of the watch. Times are FILETIME values (100 ns units)."""

    def __init__(self, *, parent_created: int = 50, opens: bool = True, times: bool = True):
        self.parent_created = parent_created
        self.opens = opens
        self.times = times
        self.ended = threading.Event()
        self.opened: list[tuple[int, bool, int]] = []
        self.waited: list[tuple[object, int]] = []
        self.closed: list[object] = []

    def OpenProcess(self, access: int, inherit: bool, pid: int) -> object:
        self.opened.append((access, inherit, pid))
        return "parent" if self.opens else None

    def GetCurrentProcess(self) -> object:
        return "self"

    def GetProcessTimes(self, process: Any, creation: Any, *_others: Any) -> int:
        if not self.times or process not in ("parent", "self"):
            return 0
        creation.contents.value = self.parent_created if process == "parent" else 100
        return 1

    def WaitForSingleObject(self, handle: object, milliseconds: int) -> int:
        self.waited.append((handle, milliseconds))
        self.ended.wait()
        return 0

    def CloseHandle(self, handle: object) -> int:
        self.closed.append(handle)
        return 1


async def test_windows_watches_the_parent_through_a_process_handle() -> None:
    k32 = FakeKernel32()
    stopped = asyncio.Event()
    codes: queue.Queue[int] = queue.Queue()
    watch = parent.watch_parent(
        77,
        stopped.set,
        asyncio.get_running_loop(),
        limit=0.0,
        hard_exit=codes.put,
        platform="win32",
        kernel32=k32,
    )
    assert watch is not None
    access = parent.SYNCHRONIZE | parent.PROCESS_QUERY_LIMITED_INFORMATION
    assert k32.opened == [(access, False, 77)]
    k32.ended.set()
    await asyncio.wait_for(stopped.wait(), 5)
    assert await asyncio.to_thread(codes.get, timeout=5) == parent.HARD_EXIT_CODE
    assert k32.waited == [("parent", parent.INFINITE)]
    assert k32.closed == ["parent"]


@pytest.mark.parametrize(
    ("k32", "closed"),
    [
        pytest.param(FakeKernel32(parent_created=200), ["parent"], id="created-after-this-one"),
        pytest.param(FakeKernel32(opens=False), [], id="cannot-be-opened"),
    ],
)
async def test_windows_a_pid_that_is_not_an_older_process_is_not_the_parent(
    k32: FakeKernel32, closed: list[object]
) -> None:
    loop = asyncio.get_running_loop()
    assert parent.watch_parent(77, lambda: None, loop, platform="win32", kernel32=k32) is None
    assert k32.closed == closed


def test_windows_a_failing_time_query_closes_the_handle() -> None:
    k32 = FakeKernel32(times=False)
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(OSError, match="GetProcessTimes"):
            parent.watch_parent(77, lambda: None, loop, platform="win32", kernel32=k32)
    finally:
        loop.close()
    assert k32.closed == ["parent"]
