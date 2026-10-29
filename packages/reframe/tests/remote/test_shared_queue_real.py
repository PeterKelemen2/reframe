"""The shared queue with real processes: ``reframe`` CLIs as subprocesses, the ``reframe-server``
that the first of them starts, and the real FFmpeg. Every process has the test's own folders;
the teardown kills the CLIs and the owners it started (an owner is known by its folder)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psutil
import pytest

from reframe.cli import EXIT_FAILED, EXIT_INTERRUPTED, EXIT_OK, STOPPED_BY_OTHERS
from reframe.models import ServerEndpoint
from reframe.platform.power import DRY_RUN_ENV
from reframe.remote.owner import ENDPOINT_FILE
from reframe_testing import media

pytestmark = [
    pytest.mark.needs_ffmpeg,
    pytest.mark.slow,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals; Windows: not run yet"),
]

WAIT = 120.0
STOP = int(getattr(signal, "SIGTSTP", 20))
GO_ON = int(getattr(signal, "SIGCONT", 18))


def _default_sigint() -> None:
    """In the child, before ``exec``: SIGINT back to its default disposition (a background
    pytest run would hand it down as ignored)."""
    signal.signal(signal.SIGINT, signal.SIG_DFL)


@dataclass
class Home:
    """Private Reframe folders, and every process a test started in them."""

    path: Path
    clients: list[subprocess.Popen[str]] = field(default_factory=list)

    @property
    def data(self) -> Path:
        return self.path / "data"

    @property
    def media(self) -> Path:
        return self.path / "media"

    @property
    def out(self) -> Path:
        return self.path / "out"

    def env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("REFRAME_")}
        for name in ("config", "data", "cache"):
            env[f"REFRAME_{name.upper()}_DIR"] = str(self.path / name)
        ffmpeg, ffprobe = media.find_ffmpeg(), media.find_ffprobe()
        assert ffmpeg is not None
        assert ffprobe is not None
        env |= {"REFRAME_FFMPEG": ffmpeg, "REFRAME_FFPROBE": ffprobe, DRY_RUN_ENV: "1"}
        env |= {"PYTHONUNBUFFERED": "1", "COLUMNS": "200"}
        return env

    def settings(self, *, parallel_jobs: int = 1) -> None:
        """Hardware tests and the sleep inhibit off; the when-done action stays "nothing",
        so no owner of a test can act on the power of this machine."""
        settings = {
            "encoders": {"hardware_tests": False},
            "queue": {"sleep_inhibit": False, "parallel_jobs": parallel_jobs},
        }
        (self.path / "config").mkdir(parents=True, exist_ok=True)
        (self.path / "config" / "settings.json").write_text(json.dumps(settings), "utf-8")

    def source(self, name: str, seconds: int) -> Path:
        """A 720p test video with a sine tone."""
        path = self.media / name
        path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = media.find_ffmpeg()
        assert ffmpeg is not None
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size=1280x720:rate=25:duration={seconds}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={seconds}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                str(path),
            ],
            check=True,
            timeout=120,
        )
        return path

    def start(self, *args: str, group: bool = False) -> subprocess.Popen[str]:
        """``reframe ARGS…`` in the background (``group``: in a process group of its own, as a
        shell starts a job; a stop signal does not stop a process of an orphaned group)."""
        process = subprocess.Popen(
            [sys.executable, "-m", "reframe.cli", *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env(),
            text=True,
            encoding="utf-8",
            preexec_fn=_default_sigint,
            process_group=0 if group else None,
        )
        self.clients.append(process)
        return process

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        process = self.start(*args)
        out, err = process.communicate(timeout=WAIT)
        return subprocess.CompletedProcess(process.args, process.returncode, out, err)

    def jobs(self) -> list[dict[str, Any]]:
        result = self.run("queue", "list", "--json")
        assert result.returncode == 0, result.stderr
        jobs: list[dict[str, Any]] = json.loads(result.stdout)
        return jobs

    def job(self, source: Path) -> dict[str, Any]:
        [job] = [j for j in self.jobs() if j["settings"]["source"]["path"] == str(source)]
        return job

    def state(self, source: Path) -> str | None:
        """The state of the job of ``source``; ``None`` before it is queued."""
        states = [j["state"] for j in self.jobs() if j["settings"]["source"]["path"] == str(source)]
        return states[0] if states else None

    def endpoint(self) -> ServerEndpoint:
        return ServerEndpoint.model_validate_json((self.data / ENDPOINT_FILE).read_bytes())

    def owners(self) -> list[psutil.Process]:
        """The running servers of this data folder (the test started them, through its CLIs)."""
        found = []
        for process in psutil.process_iter(["cmdline", "environ"]):
            try:
                cmdline = " ".join(process.info["cmdline"] or [])
                environ = process.info["environ"] or {}
            except (psutil.Error, OSError):
                continue
            if "reframe_server" in cmdline and environ.get("REFRAME_DATA_DIR") == str(self.data):
                found.append(process)
        return found

    def stop_everything(self) -> None:
        for process in self.clients:
            if process.poll() is None:
                process.kill()
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            process.wait(30)
        for owner in self.owners():
            owner.kill()
            owner.wait(30)


@pytest.fixture
def home(tmp_path: Path) -> Iterator[Home]:
    found = Home(tmp_path / "home")
    found.settings()
    found.out.mkdir(parents=True)
    try:
        yield found
    finally:
        found.stop_everything()


def wait_until(check: Callable[[], Any], limit: float = WAIT) -> Any:
    deadline = time.monotonic() + limit
    while not (result := check()):
        assert time.monotonic() < deadline, "not in time"
        time.sleep(0.1)
    return result


def read_until(process: subprocess.Popen[str], check: Callable[[str], bool]) -> list[str]:
    """``process``'s stdout lines up to the first line for which ``check`` holds."""
    assert process.stdout is not None
    lines: list[str] = []
    deadline = time.monotonic() + WAIT
    for line in process.stdout:
        lines.append(line.rstrip("\n"))
        if check(lines[-1]):
            return lines
        assert time.monotonic() < deadline, lines
    raise AssertionError(f"the process ended first: {lines}")


def encoding(line: str) -> bool:
    return line.startswith("[1/1] ") and "% · " in line and "[1/1] 0.0%" not in line


def finish(
    process: subprocess.Popen[str], before: list[str] | None = None
) -> tuple[list[str], str]:
    """The rest of ``process``'s stdout lines (through the same reader as :func:`read_until`:
    ``communicate`` would miss what it has buffered) and its stderr, once it has ended."""
    assert process.stdout is not None
    assert process.stderr is not None
    with process.stdout, process.stderr:
        lines = [*(before or []), *(line.rstrip("\n") for line in process.stdout)]
        err = process.stderr.read()
    process.wait(WAIT)
    return lines, err


def test_two_encodes_at_once_both_finish_and_share_the_slot_limit(home: Home) -> None:
    first, second = home.source("a/First.mkv", 8), home.source("b/Second.mkv", 8)
    clients = [
        home.start("encode", str(source), "-o", str(home.out / source.name))
        for source in (first, second)
    ]
    results = [finish(client) for client in clients]
    for client, (lines, err) in zip(clients, results, strict=True):
        assert client.returncode == EXIT_OK, (lines, err)
        assert lines[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 0 not queued.", lines
        assert any(line.startswith("[1/1] ") and "% · " in line for line in lines), lines
    for (lines, _), source, other in ((results[0], first, second), (results[1], second, first)):
        text = "\n".join(lines)
        assert source.name in text
        assert other.name not in text  # each client shows its own job only
    jobs = sorted(home.jobs(), key=lambda job: job["started_at"])
    assert [job["state"] for job in jobs] == ["done", "done"]
    assert jobs[0]["finished_at"] <= jobs[1]["started_at"]  # parallel_jobs is 1
    assert jobs[1]["created_at"] < jobs[0]["finished_at"]  # it waited for the first one
    [owner] = home.owners()
    assert owner.environ().get(DRY_RUN_ENV) == "1"  # its when-done action never reaches the OS


def test_sigint_in_one_client_cancels_only_its_own_jobs(home: Home) -> None:
    """Two slots: the other client's job runs next to this one's at the SIGINT, and runs on."""
    home.settings(parallel_jobs=2)
    first, second = home.source("a/First.mkv", 60), home.source("b/Second.mkv", 8)
    one = home.start("encode", str(first), "-o", str(home.out / "First.mkv"))
    seen = read_until(one, encoding)
    other = home.start("encode", str(second), "-o", str(home.out / "Second.mkv"))
    read_until(other, encoding)
    assert list(home.out.glob("First.part.*")), seen
    one.send_signal(signal.SIGINT)
    lines, err = finish(one, seen)
    assert one.returncode == EXIT_INTERRUPTED, (lines, err)
    assert "Interrupted: cancelling the jobs" in err
    assert lines[-1] == "Summary: 0 done, 0 failed, 1 cancelled, 0 not queued."
    assert home.job(first)["state"] == "cancelled"
    assert not list(home.out.glob("First.part.*"))
    other_lines, other_err = finish(other)
    assert other.returncode == EXIT_OK, (other_lines, other_err)
    assert home.job(second)["state"] == "done"


def test_kill_9_of_a_client_cancels_its_jobs_and_a_detached_job_runs_on(home: Home) -> None:
    home.settings(parallel_jobs=2)
    attached, detached = home.source("a/Attached.mkv", 60), home.source("b/Detached.mkv", 60)
    client = home.start("encode", str(attached), "-o", str(home.out / "Attached.mkv"))
    seen = read_until(client, encoding)
    result = home.run("encode", "--detach", str(detached), "-o", str(home.out / "Detached.mkv"))
    assert result.returncode == EXIT_OK, (result.stdout, result.stderr)
    job = home.job(detached)
    assert f"[1/1] job {job['id']}" in result.stdout
    wait_until(lambda: home.state(detached) == "running")
    assert list(home.out.glob("Attached.part.*")), seen
    client.kill()
    client.wait(WAIT)
    wait_until(lambda: home.state(attached) == "cancelled")
    assert not list(home.out.glob("Attached.part.*"))
    time.sleep(1.0)
    assert home.job(detached)["state"] == "running"
    cancel = home.run("queue", "cancel", job["id"][:8])
    assert cancel.returncode == EXIT_OK, cancel.stderr


def test_kill_9_of_the_server_interrupts_the_job_and_the_next_command_restores_the_queue(
    home: Home,
) -> None:
    source, short = home.source("a/Long.mkv", 60), home.source("b/Short.mkv", 4)
    client = home.start("encode", str(source), "-o", str(home.out / "Long.mkv"))
    seen = read_until(client, encoding)
    [owner] = home.owners()
    assert owner.pid == home.endpoint().pid
    owner.kill()
    lines, err = finish(client, seen)
    assert client.returncode == EXIT_FAILED, (lines, err)
    assert "[1/1] interrupted" in lines
    assert lines[-1] == "Summary: 0 done, 0 failed, 0 cancelled, 1 interrupted, 0 not queued."
    assert "the connection to the Reframe server was lost" in err
    assert home.job(source)["state"] == "running"  # the saved queue, read as it is
    result = home.run("encode", str(short), "-o", str(home.out / "Short.mkv"))
    assert result.returncode == EXIT_OK, (result.stdout, result.stderr)
    [new_owner] = home.owners()
    assert new_owner.pid != owner.pid
    restored = home.job(source)
    assert restored["state"] == "interrupted"
    assert restored["error"].startswith("Reframe stopped while the job was running.")
    assert not list(home.out.glob("Long.part.*"))


def test_ten_clients_that_add_jobs_at_once_lose_none_and_duplicate_none(home: Home) -> None:
    sources = [home.source(f"s{n}/Show.S01E{n:02d}.mkv", 2) for n in range(1, 11)]
    clients = [
        home.start("encode", "--detach", str(source), "-o", str(home.out / source.name))
        for source in sources
    ]
    for client in clients:
        lines, err = finish(client)
        assert client.returncode == EXIT_OK, (lines, err)
    jobs = home.jobs()
    assert len(jobs) == 10
    assert len({job["id"] for job in jobs}) == 10
    assert sorted(job["settings"]["source"]["path"] for job in jobs) == sorted(map(str, sources))
    assert len(home.owners()) == 1
    cancel = home.run("queue", "cancel", "--all")
    assert cancel.returncode == EXIT_OK, cancel.stderr


def test_a_job_whose_output_another_clients_waiting_job_writes_is_added_failed(
    home: Home,
) -> None:
    busy, first, second = (
        home.source("a/Busy.mkv", 60),
        home.source("b/First.mkv", 4),
        home.source("c/Second.mkv", 4),
    )
    target = home.out / "Same.mkv"
    assert (
        home.run("encode", "--detach", str(busy), "-o", str(home.out / "Busy.mkv")).returncode == 0
    )
    assert home.run("encode", "--detach", str(first), "-o", str(target)).returncode == 0
    assert home.job(first)["state"] == "waiting"  # the one slot is the busy job's
    result = home.run("encode", str(second), "-o", str(target))
    assert result.returncode == EXIT_FAILED
    assert "[1/1] failed when it was queued:" in result.stdout
    assert "is also the output of a job that is waiting in the queue (First.mkv)" in result.stdout
    claimed = home.job(second)
    assert claimed["state"] == "failed"
    assert [i["code"] for i in claimed["issues"] if i["severity"] == "error"] == [
        "queue.output_claimed"
    ]
    assert home.job(first)["state"] == "waiting"
    assert home.run("queue", "cancel", "--all").returncode == EXIT_OK


OTHER_API = """
import sys
import reframe_server.api, reframe_server.owner
import reframe_server.routers.health as health
for module in (reframe_server.api, reframe_server.owner, health):
    module.API_VERSION = 2
from reframe_server.__main__ import main
sys.exit(main(["--mode", "desktop", "--port", "0"]))
"""


def test_a_server_of_another_api_version_is_not_used_and_the_client_says_why(home: Home) -> None:
    server = subprocess.Popen(
        [sys.executable, "-c", OTHER_API],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=home.env(),
        text=True,
    )
    home.clients.append(server)
    wait_until(lambda: (home.data / ENDPOINT_FILE).exists())
    assert home.endpoint().api_version == 2
    source = home.source("a/Show.mkv", 2)
    result = home.run("encode", str(source), "-o", str(home.out / "Show.mkv"))
    assert result.returncode == EXIT_OK, (result.stdout, result.stderr)
    assert (
        f"warning: no Reframe server can take the jobs (Reframe 0.1.0.dev0 (pid {server.pid}) "
        "owns the queue, and it speaks API version 2, not 1 as this reframe does): they run "
        "in this process."
    ) in result.stderr
    assert f"Another Reframe process (pid {server.pid}) is using the saved queue" in result.stderr
    assert "Queue: Reframe" not in result.stdout
    assert result.stdout.splitlines()[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 0 not queued."
    assert server.poll() is None
    assert home.jobs() == []  # the server's saved queue: the job ran in the client's own


def test_a_waiting_job_that_another_client_removes_ends_the_follow(home: Home) -> None:
    """``reframe queue remove`` of a waiting job of ``reframe encode A B``: the command reports
    it, ends when A is done, and says so in its exit code."""
    a, b = home.source("a/A.mkv", 8), home.source("b/B.mkv", 2)
    client = home.start("encode", str(a), str(b))
    seen = read_until(client, lambda line: line.startswith("[1/2] ") and "% · " in line)
    removed = home.run("queue", "remove", home.job(b)["id"][:8])
    assert removed.returncode == EXIT_OK, removed.stderr
    lines, err = finish(client, seen)
    assert client.returncode == EXIT_FAILED, (lines, err)
    assert "[2/2] removed" in lines
    assert lines[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 1 removed, 0 not queued."
    assert [job["state"] for job in home.jobs()] == ["done"]


def test_ctrl_z_pauses_the_job_and_fg_resumes_it(home: Home) -> None:
    """SIGTSTP (the terminal's Ctrl+Z): while the command is stopped its job is paused in the
    owner and the command holds no connection; SIGCONT (``fg``) resumes the job."""
    source = home.source("a/Show.mkv", 8)
    client = home.start("encode", str(source), "-o", str(home.out / "Show.mkv"), group=True)
    seen = read_until(client, encoding)
    [owner] = home.owners()
    port = home.endpoint().port
    client.send_signal(STOP)
    process = psutil.Process(client.pid)
    wait_until(lambda: process.status() == psutil.STATUS_STOPPED, 30)
    assert home.job(source)["state"] == "paused"
    held = [c for c in process.net_connections() if c.raddr and c.raddr.port == port]
    assert held == []
    time.sleep(1.0)
    assert home.job(source)["state"] == "paused"
    client.send_signal(GO_ON)
    lines, err = finish(client, seen)
    assert client.returncode == EXIT_OK, (lines, err)
    assert "Stopped" in err
    assert "[1/1] resumed" in lines
    assert lines[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 0 not queued."
    assert owner.is_running()


def read_within(
    process: subprocess.Popen[str], check: Callable[[str], bool], seconds: float = 60.0
) -> list[str]:
    """:func:`read_until` for a line that a waiting process may never print: it is killed after
    ``seconds``, so the read ends."""
    timer = threading.Timer(seconds, process.kill)
    timer.start()
    try:
        return read_until(process, check)
    finally:
        timer.cancel()


def owner_api(home: Home) -> httpx.Client:
    """The owner's REST API, as another front end (the UI) calls it."""
    endpoint = home.endpoint()
    return httpx.Client(
        base_url=f"http://127.0.0.1:{endpoint.port}",
        headers={"Authorization": f"Bearer {endpoint.token}"},
        timeout=30,
    )


def test_a_stop_by_another_front_end_is_reported_and_the_jobs_wait_for_a_start(
    home: Home,
) -> None:
    """The UI's Stop while the jobs of two commands wait behind a busy job: each command says so
    and goes on waiting, also once the slot is free; Ctrl+C still cancels one command's job,
    and the UI's Start runs the other's."""
    busy = home.source("a/Busy.mkv", 60)
    first, second = home.source("b/First.mkv", 2), home.source("c/Second.mkv", 2)
    result = home.run("encode", "--detach", str(busy), "-o", str(home.out / "Busy.mkv"))
    assert result.returncode == EXIT_OK, (result.stdout, result.stderr)
    wait_until(lambda: home.state(busy) == "running")
    clients = [
        home.start("encode", str(source), "-o", str(home.out / source.name))
        for source in (first, second)
    ]
    with owner_api(home) as api:

        def started() -> bool:
            """Both commands' starts are in."""
            body = api.get("/api/queue").json()
            paths = (str(first), str(second))
            ids = {j["id"] for j in body["jobs"] if j["settings"]["source"]["path"] in paths}
            return len(ids) == 2 and body["processing"] and ids <= set(body["only"] or ())

        wait_until(started)
        assert api.post("/api/queue/stop").status_code == 204
        seen = [read_within(client, lambda line: line == STOPPED_BY_OTHERS) for client in clients]
        assert home.run("queue", "cancel", home.job(busy)["id"][:8]).returncode == EXIT_OK
        time.sleep(1.0)  # a job that the runner took would be running by now
        assert [home.state(first), home.state(second)] == ["waiting", "waiting"]
        assert [client.poll() for client in clients] == [None, None]
        clients[1].send_signal(signal.SIGINT)
        lines, err = finish(clients[1], seen[1])
        assert clients[1].returncode == EXIT_INTERRUPTED, (lines, err)
        assert lines[-1] == "Summary: 0 done, 0 failed, 1 cancelled, 0 not queued."
        assert home.state(second) == "cancelled"
        assert api.post("/api/queue/start").status_code == 204
    lines, err = finish(clients[0], seen[0])
    assert clients[0].returncode == EXIT_OK, (lines, err)
    assert lines.count(STOPPED_BY_OTHERS) == 1
    assert lines[-1] == "Summary: 1 done, 0 failed, 0 cancelled, 0 not queued."
    assert home.state(first) == "done"
