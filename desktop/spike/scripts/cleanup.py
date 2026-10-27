"""Cleanup proofs: the spike app runs an x265 encode of ``hdr10-4k.mkv`` through its frozen
sidecar, then the app is killed (``app-kill``), the sidecar alone is killed
(``sidecar-kill``), or the app quits as a closed window does (``quit``). Prints the processes
before and after, how long they took to go, and what became of the job and its ``.part`` file
(read by a new sidecar in the same folders)."""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import psutil
from desktop.spike.scripts import app, cold_start, sidecar, windows
from desktop.spike.scripts.spike_paths import APP, FROZEN_SERVER, SIDECAR_ONEDIR

GONE_LIMIT = 20.0
SIGKILL: int = getattr(signal, "SIGKILL")  # noqa: B009 - the spike runs on Linux


def show(title: str, pids: list[int], patterns: list[str]) -> None:
    print(f"--- {title}")
    listed = subprocess.run(
        ["ps", "-o", "pid,ppid,stat,etime,args", "-p", ",".join(map(str, pids))],
        capture_output=True,
        text=True,
    ).stdout
    print(f"$ ps -o pid,ppid,stat,etime,args -p {','.join(map(str, pids))}")
    print(listed.rstrip() or "(nothing)")
    for pattern in patterns:
        found = subprocess.run(["pgrep", "-af", pattern], capture_output=True, text=True).stdout
        print(f"$ pgrep -af '{pattern}'")
        print(found.rstrip() or "(nothing)")


def started(pid: int) -> tuple[str, int] | None:
    """The state and the start time (clock ticks after boot, field 22) of ``/proc/<pid>/stat``;
    ``None`` when there is no such process."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return None
    fields = text.rsplit(") ", 1)[1].split()
    return fields[0], int(fields[19])


@dataclass(frozen=True)
class Tracked:
    """A process by its pid and start time: a later process that got the same pid is not it."""

    pid: int
    start: int

    @classmethod
    def of(cls, pid: int) -> Tracked:
        found = started(pid)
        if found is None:
            raise ProcessLookupError(pid)
        return cls(pid, found[1])

    def running(self) -> bool:
        """The same process, and not a zombie."""
        found = started(self.pid)
        return found is not None and found[1] == self.start and found[0] != "Z"


def alive(tracked: list[Tracked]) -> list[Tracked]:
    return [process for process in tracked if process.running()]


def kill(tracked: list[Tracked]) -> None:
    """SIGKILL to each tracked process that still runs (a reused pid is left alone)."""
    for process in alive(tracked):
        with contextlib.suppress(ProcessLookupError):
            os.kill(process.pid, SIGKILL)


def wait_gone(tracked: list[Tracked], limit: float = GONE_LIMIT) -> float | None:
    """Seconds until none of ``tracked`` runs (a zombie counts as gone); ``None``: not in time."""
    began = time.monotonic()
    while alive(tracked):
        if time.monotonic() - began > limit:
            return None
        time.sleep(0.01)
    return time.monotonic() - began


def job_after(home: Path, job_id: str, part: Path) -> dict[str, Any]:
    """The job's state and ``.part`` file as a new sidecar in the same folders sees them."""
    result: dict[str, Any] = {"part right after": part.exists()}
    car = sidecar.start(sidecar.frozen_command(), home)
    try:
        result["state at the next start"] = car.job(job_id)["state"]
        time.sleep(2)
        result["part 2 s after the next start"] = part.exists()
        car.client.post("/api/system/shutdown")
        windows.reap(car.process, 15)
    finally:
        car.close()
        if car.process.poll() is None:
            car.process.kill()
            car.process.wait()
    return result


def run(case: str, *, death_signal: bool, parent_watch: bool) -> dict[str, Any]:
    env = {"REFRAME_SPIKE_REPORT_TOKEN": "1"}
    if not death_signal:
        env["REFRAME_SPIKE_NO_DEATH_SIGNAL"] = "1"
    if not parent_watch:
        env["REFRAME_SPIKE_NO_PARENT_PID"] = "1"
    with tempfile.TemporaryDirectory(prefix="reframe-spike-") as tmp:
        home = Path(tmp)
        shell = app.start(home, extra_env=env)
        try:
            return proof(case, shell, home)
        finally:
            if shell.process.poll() is None:
                shell.process.kill()
            shell.process.wait()


def proof(case: str, shell: app.App, home: Path) -> dict[str, Any]:
    shell.wait_event("page_health")
    ready = shell.events["sidecar_ready"]
    api = sidecar.Api(ready["port"], ready["token"], home)
    source = home / "media" / "hdr10-4k.mkv"
    source.parent.mkdir()
    shutil.copyfile(sidecar.MEDIA / "hdr10-4k.mkv", source)
    job_id = api.encode(source, home / "out" / "encoded.mkv")
    job = api.wait_encoding(job_id)
    api.close()
    part = Path(job["plan"]["output_tmp"])
    shell_process = Tracked.of(shell.process.pid)
    server = Tracked.of(shell.events["sidecar_spawned"]["pid"])
    encoders = [
        Tracked.of(child.pid) for child in psutil.Process(server.pid).children(recursive=True)
    ]
    tracked = [shell_process, server, *encoders]
    pids = [process.pid for process in tracked]
    patterns = [str(APP), f"{SIDECAR_ONEDIR.name}/{FROZEN_SERVER.name}", f"ffmpeg.*{home}"]
    show("before", pids, patterns)
    print(f".part file: {part} exists={part.exists()} size={part.stat().st_size}")
    acted = time.monotonic()
    if case == "app-kill":
        shell.process.kill()
        took = wait_gone(tracked)
    elif case == "sidecar-kill":
        kill([server])
        took = wait_gone([server, *encoders])
        shell.wait_event("page_failed")
    else:
        shell.quit()
        took = wait_gone(tracked)
    show(f"after ({case})", pids, patterns)
    result: dict[str, Any] = {
        "case": case,
        "gone after (s)": None if took is None else round(took, 3),
        "still running": [process.pid for process in alive(tracked)],
    }
    if case == "sidecar-kill":
        failed = shell.events["page_failed"]
        result["app shows"] = failed["message"]
        result["app shows after (s)"] = round(failed["seen"] - (acted - shell.spawned_at), 3)
        result["app still running"] = shell_process.running()
        shell.quit()
        windows.reap(shell.process, 10)
    if case == "quit":
        result["app saw"] = shell.wait_event("sidecar_stopped")
    kill(tracked)
    wait_gone(tracked)
    result |= job_after(home, job_id, part)
    log = shell.log.read_text(errors="replace")
    result["sidecar log"] = [
        line for line in log.splitlines() if "parent" in line or "Shutting down" in line
    ]
    return result


class Tee(io.TextIOBase):
    """Writes to stdout and to a file."""

    def __init__(self, stdout: TextIO, file: TextIO) -> None:
        self.streams = (stdout, file)

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=["app-kill", "sidecar-kill", "quit"])
    parser.add_argument("--no-death-signal", action="store_true", help="no PR_SET_PDEATHSIG")
    parser.add_argument("--no-parent-pid", action="store_true", help="no --parent-pid watch")
    parser.add_argument(
        "--out",
        type=Path,
        help="also write the output here (default: results/cleanup-<machine>-<date>-<case>.out)",
    )
    parser.add_argument("--machine", default=socket.gethostname(), help="for the file name")
    args = parser.parse_args(argv)
    flags = [("-no-death-signal", args.no_death_signal), ("-no-parent-pid", args.no_parent_pid)]
    ending = f"-{args.case}{''.join(flag for flag, on in flags if on)}.out"
    target = args.out or cold_start.results_file("cleanup", args.machine, ending)
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        target.open("w", encoding="utf-8") as file,
        contextlib.redirect_stdout(Tee(sys.stdout, file)),
    ):
        print(f"loadavg before: {cold_start.loadavg()}")
        result = run(
            args.case, death_signal=not args.no_death_signal, parent_watch=not args.no_parent_pid
        )
        print("--- result")
        for key, value in result.items():
            print(f"{key}: {value}")
        print(f"loadavg after: {cold_start.loadavg()}")
    print(f"output: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
