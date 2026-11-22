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
from pydantic import SecretStr

from reframe_server import parent
from reframe_server.__main__ import serve
from reframe_server.config import ServerConfig
from reframe_testing import media
from reframe_testing.processes import ready_port
from reframe_testing.waiting import wait_until_sync

pytestmark = pytest.mark.anyio

TOKEN = "parent-test-" + "x" * 32


LINUX = pytest.mark.skipif(sys.platform != "linux", reason="/proc and pidfd: Linux only")


def stand_in(executable: str | Path = sys.executable) -> subprocess.Popen[bytes]:
    """A process that waits until it is killed: the desktop shell of a test."""
    return subprocess.Popen([str(executable), "-c", "import time; time.sleep(600)"])


def older_stand_in() -> subprocess.Popen[bytes]:
    """A stand-in for a server started later. It is not the server's ancestor, so it must have
    started a clock tick (10 ms) before the server."""
    process = stand_in()
    time.sleep(0.03)
    return process


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


def start_encode(client: httpx.Client, source: Path, output: Path) -> dict[str, Any]:
    """An x265 encode of ``source`` that runs for a while; returns the job once it writes."""
    accepted = client.post("/api/sources", json={"paths": [str(source)]}).json()

    def probed() -> Any:
        task = client.get(f"/api/tasks/{accepted['task_id']}").json()
        return task["result"] if task["state"] == "done" else None

    source_id = wait_until_sync(probed, 60)["sources"][0]["id"]
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

    job_now: dict[str, Any] = wait_until_sync(writing, 60)
    return job_now


def ffmpeg_processes(pid: int) -> list[psutil.Process]:
    return [p for p in psutil.Process(pid).children(recursive=True) if "ffmpeg" in p.name()]


@pytest.fixture
def shell() -> Iterator[subprocess.Popen[bytes]]:
    process = older_stand_in()
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
        base_url = f"http://127.0.0.1:{ready_port(server, 60)}"
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


async def test_a_process_younger_than_the_server_is_not_its_parent(tmp_path: Path) -> None:
    """The parent ended and the OS gave its pid to a new process before the watch began. Its
    name holds ")" and a space, as ``/proc/<pid>/stat`` shows a name."""
    executable: str | Path = sys.executable
    if sys.platform == "linux":
        executable = tmp_path / "a) b"
        executable.symlink_to(sys.executable)
    younger = stand_in(executable)
    try:
        watch = parent.watch_parent(
            younger.pid, lambda: None, asyncio.get_running_loop(), hard_exit=lambda _code: None
        )
        assert watch is None
    finally:
        younger.kill()
        younger.wait()


WATCH_IN_A_NEW_PROCESS = """
import asyncio, json, os, sys
from pathlib import Path
from reframe_server import parent

def stat(pid):
    return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()

async def main():
    which = sys.argv[1]
    if which == "parent":
        pid = os.getppid()
    elif which == "grandparent":
        pid = int(stat(os.getppid())[1])
    else:
        pid = int(sys.stdin.readline())
    loop = asyncio.get_running_loop()
    watch = parent.watch_parent(pid, lambda: None, loop, hard_exit=lambda _code: None)
    same = stat(pid)[19] == stat("self")[19]
    print(json.dumps({"same_tick": same, "watched": watch is not None}))

asyncio.run(main())
"""


@LINUX
@pytest.mark.parametrize(
    ("launcher", "which", "watched"),
    [
        pytest.param(["timeout", "60"], "parent", True, id="parent"),
        pytest.param(["timeout", "60", "timeout", "60"], "grandparent", True, id="grandparent"),
        pytest.param([], "younger", False, id="younger-not-an-ancestor"),
    ],
)
def test_a_process_of_the_servers_clock_tick_is_its_parent_only_when_it_is_an_ancestor(
    launcher: list[str], which: str, watched: bool
) -> None:
    """A launcher such as ``timeout`` forks the server in its own start tick (10 ms), so the
    tick cannot tell a parent from a process that got the parent's pid in that tick."""
    for _ in range(50):
        checker = subprocess.Popen(
            [*launcher, sys.executable, "-c", WATCH_IN_A_NEW_PROCESS, which],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        younger = stand_in() if which == "younger" else None
        try:
            given = f"{younger.pid}\n".encode() if younger else b""
            out, _ = checker.communicate(given, timeout=30)
        finally:
            if younger is not None:
                younger.kill()
                younger.wait()
        result = json.loads(out)
        if result["same_tick"]:
            assert result["watched"] is watched
            return
    pytest.fail("the processes never started in the same clock tick")


@pytest.mark.usefixtures("make_api")  # the test's own folders, tools and settings
async def test_a_server_stopped_by_request_ignores_its_parents_end_afterwards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The shell asks its sidecar to stop and then exits: the server ends with 0 and no hard
    exit follows the shell's end."""
    ended, released = threading.Event(), threading.Event()
    codes: queue.Queue[int] = queue.Queue()

    def watch(pid: int, stop: Callable[[], None], loop: asyncio.AbstractEventLoop) -> Any:
        return parent.ParentWatch(pid, ended.wait, released.set, stop, loop, 0.2, codes.put)

    monkeypatch.setattr(parent, "watch_parent", watch)
    config = ServerConfig(
        mode="desktop",
        parent_pid=4242,
        token=SecretStr(TOKEN),
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
    )
    serving = asyncio.create_task(serve(config))
    printed = ""
    while not printed:
        assert not serving.done()
        await asyncio.sleep(0.02)
        printed = capsys.readouterr().out
    port = json.loads(printed)["port"]
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=headers) as client:
        assert (await client.post("/api/system/shutdown")).status_code == 204
    assert await asyncio.wait_for(serving, 30) == 0
    ended.set()
    assert await asyncio.to_thread(released.wait, 5)
    await asyncio.sleep(0.5)
    assert codes.empty()


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
    assert code == 70
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
    assert codes.get(timeout=5) == 70


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
    assert await asyncio.to_thread(codes.get, timeout=5) == 70
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
