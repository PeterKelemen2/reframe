"""Cleanup proofs: the spike app runs an x265 encode of ``hdr10-4k.mkv`` through its frozen
sidecar, then the app is killed (``app-kill``), the sidecar alone is killed
(``sidecar-kill``), or the app quits as a closed window does (``quit``). Prints the processes
before and after, how long they took to go, and what became of the job and its ``.part`` file
(read by a new sidecar in the same folders)."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil
from desktop.spike.scripts import app, sidecar
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


def alive(pids: list[int]) -> list[int]:
    living = []
    for pid in pids:
        try:
            if psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
                living.append(pid)
        except psutil.NoSuchProcess:
            pass
    return living


def wait_gone(pids: list[int], limit: float = GONE_LIMIT) -> float | None:
    """Seconds until none of ``pids`` runs (a zombie counts as gone); ``None``: not in time."""
    began = time.monotonic()
    while alive(pids):
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
        car.process.wait(15)
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
            leftovers = alive([shell.process.pid])
            for pid in leftovers:
                os.kill(pid, SIGKILL)
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
    server = shell.events["sidecar_spawned"]["pid"]
    encoders = [p.pid for p in psutil.Process(server).children(recursive=True)]
    tracked = [shell.process.pid, server, *encoders]
    patterns = [str(APP), f"{SIDECAR_ONEDIR.name}/{FROZEN_SERVER.name}", f"ffmpeg.*{home}"]
    show("before", tracked, patterns)
    print(f".part file: {part} exists={part.exists()} size={part.stat().st_size}")
    acted = time.monotonic()
    if case == "app-kill":
        os.kill(shell.process.pid, SIGKILL)
        took = wait_gone(tracked)
    elif case == "sidecar-kill":
        os.kill(server, SIGKILL)
        took = wait_gone([server, *encoders])
        shell.wait_event("page_failed")
    else:
        shell.quit()
        took = wait_gone(tracked)
    show(f"after ({case})", tracked, patterns)
    result: dict[str, Any] = {
        "case": case,
        "gone after (s)": None if took is None else round(took, 3),
        "still running": alive(tracked),
    }
    if case == "sidecar-kill":
        failed = shell.events["page_failed"]
        result["app shows"] = failed["message"]
        result["app shows after (s)"] = round(failed["seen"] - (acted - shell.spawned_at), 3)
        result["app still running"] = bool(alive([shell.process.pid]))
        shell.quit()
        shell.process.wait(10)
    if case == "quit":
        result["app saw"] = shell.wait_event("sidecar_stopped")
    for pid in alive(tracked):
        os.kill(pid, SIGKILL)
    wait_gone(tracked)
    result |= job_after(home, job_id, part)
    log = shell.log.read_text(errors="replace")
    result["sidecar log"] = [
        line for line in log.splitlines() if "parent" in line or "Shutting down" in line
    ]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=["app-kill", "sidecar-kill", "quit"])
    parser.add_argument("--no-death-signal", action="store_true", help="no PR_SET_PDEATHSIG")
    parser.add_argument("--no-parent-pid", action="store_true", help="no --parent-pid watch")
    args = parser.parse_args(argv)
    result = run(
        args.case, death_signal=not args.no_death_signal, parent_watch=not args.no_parent_pid
    )
    print("--- result")
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
