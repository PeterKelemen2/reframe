"""One process owns the queue store (decision 0027, M2 review finding B1).

A second Reframe process on the same data folder must not touch the first one's jobs: before
the fix, every ``Reframe.create()`` restored the store, marked the other process's running job
``interrupted`` and removed its ``.part`` file. These tests run real processes."""

from __future__ import annotations

import asyncio
import errno
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import psutil
import pytest

from reframe.models import JobState
from reframe.queue.lock import (
    LOCK_FILE,
    WINDOWS_LOCK_OFFSET,
    MsvcrtBackend,
    StoreLock,
    default_backend,
)
from reframe.service import Reframe
from reframe_testing import fake_tools as ft

from .conftest import draft, encode_rule, poll, recorded
from .test_facade import PROBE, env  # noqa: F401  (the fixture)

pytestmark = pytest.mark.anyio

#: A second Reframe process: ``create()`` and ``close()`` only, or a whole encode of the job
#: given as JSON. It prints one JSON line: the end state and the ``app.warning`` codes.
CHILD = """
import asyncio, json, sys
from reframe.probe import mediainfo
mediainfo.mediainfo_available = lambda: False
from reframe.models import JobSettings
from reframe.service import Reframe

async def main(mode, job_json):
    async with await Reframe.create() as app:
        result = {"state": None, "warnings": []}
        if mode == "encode":
            warnings = app.events.subscribe(types={"app.warning"})
            added = await app.queue.add(JobSettings.model_validate_json(job_json))
            app.queue.start(job_ids=[added.id])
            [ended] = await app.queue.wait([added.id])
            result["state"] = ended.state.value
            result["error"] = ended.error
            while (event := warnings.get_nowait()) is not None:
                result["warnings"].append([event.code, event.message])
        elif mode == "hold":
            added = await app.queue.add(JobSettings.model_validate_json(job_json))
            progress = app.events.subscribe(types={"job.progress"})
            app.queue.start()
            async for event in progress:
                break
            print("running", flush=True)
            await asyncio.sleep(120)
        print(json.dumps(result), flush=True)

asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
"""


def child(mode: str, job: str = "") -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-c", CHILD, mode, job],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result: dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
    return result


async def test_a_second_process_leaves_a_running_encode_alone(
    env: Path,  # noqa: F811
    fake_tools: ft.FakeTools,
) -> None:
    """Terminal 1 encodes; terminal 2 runs a command (``create()`` + ``close()``), then a
    whole ``encode``. The first job finishes ``done``; the second runs on a private queue."""
    fake_tools.set_scenario(
        ft.Scenario(
            [
                PROBE,
                ft.Rule(
                    argv_contains=["First.part.mkv"],
                    actions=[
                        ft.progress(blocks=1, end=False),
                        ft.write_output(4096),
                        ft.sleep(2.5),  # the .part file must still be there afterwards
                        ft.progress(blocks=1),
                    ],
                ),
            ]
        )
    )
    source = recorded("multitrack.mkv", env / "media" / "Show.mkv")
    app = await Reframe.create()
    try:
        first = await app.queue.add(draft(source, env / "out" / "First.mkv"))
        app.queue.start()
        progress = app.events.subscribe(types={"job.progress"})
        async for _ in progress:
            break
        part = env / "out" / "First.part.mkv"
        await poll(part.exists)
        quiet = await asyncio.to_thread(child, "create")
        assert quiet == {"state": None, "warnings": []}
        assert part.exists()
        db = sqlite3.connect(env / "data" / "queue.sqlite3")
        try:  # the saved row still says running: the child did not restore the store
            [(state,)] = db.execute("SELECT state FROM jobs WHERE id = ?", (first.id,))
        finally:
            db.close()
        assert state == "running"
        second = draft(source, env / "out" / "Second.mkv").model_dump_json()
        other = await asyncio.to_thread(child, "encode", second)
        assert other["state"] == "done", other
        [[code, message]] = other["warnings"]
        assert code == "queue.store_busy"
        assert message == (
            f"Another Reframe process (pid {os.getpid()}) is using the saved queue. The jobs "
            "of this process run here and are not kept after it ends."
        )
        [ended] = await app.queue.wait([first.id])
        assert ended.state is JobState.DONE, ended.error
        assert (env / "out" / "First.mkv").stat().st_size == 4096
        assert (env / "out" / "Second.mkv").exists()
    finally:
        await app.close()
    again = await Reframe.create()
    try:  # only the owner's job is in the saved queue
        assert [(j.id, j.state) for j in again.queue.list()] == [(first.id, JobState.DONE)]
    finally:
        await again.close()


async def test_create_and_close_without_the_queue_touch_nothing(env: Path) -> None:  # noqa: F811
    app = await Reframe.create()
    await app.tools.status()
    await app.close()
    assert not (env / "data" / "queue.sqlite3").exists()
    assert not (env / "data" / LOCK_FILE).exists()


async def test_after_the_owner_is_killed_a_new_process_restores(
    env: Path,  # noqa: F811
    fake_tools: ft.FakeTools,
) -> None:
    hang = encode_rule(ft.progress(blocks=1, end=False), ft.write_output(100), ft.hang())
    fake_tools.set_scenario(ft.Scenario([PROBE, hang]))
    source = recorded("multitrack.mkv", env / "media" / "Show.mkv")
    job = draft(source, env / "out" / "Killed.mkv").model_dump_json()
    owner = await asyncio.create_subprocess_exec(
        sys.executable, "-c", CHILD, "hold", job, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        assert owner.stdout is not None
        async with asyncio.timeout(60):
            line = await owner.stdout.readline()
        assert line.strip() == b"running"
        lock = env / "data" / LOCK_FILE
        assert lock.read_text().strip() == str(owner.pid)
        busy = StoreLock(lock).acquire()
        assert (busy.owned, busy.owner) == (False, owner.pid)
        psutil.Process(owner.pid).kill()  # SIGKILL: no clean-up runs
        await owner.wait()
    finally:
        if owner.returncode is None:
            owner.kill()
            await owner.wait()
    fake_tools.kill_leftovers()
    app = await Reframe.create()
    try:
        [restored] = app.queue.list()  # the first use takes the lock and restores
        assert restored.state is JobState.INTERRUPTED
        assert restored.error == "Reframe stopped while the job was running."
        assert lock.read_text().strip() == str(os.getpid())
        await poll(lambda: not (env / "out" / "Killed.part.mkv").exists())
    finally:
        await app.close()


# --------------------------------------------------------------------------- the lock


def test_two_owners_in_one_process_conflict(tmp_path: Path) -> None:
    path = tmp_path / "data" / LOCK_FILE
    first, second = StoreLock(path), StoreLock(path)
    assert first.acquire().owned
    assert first.acquire().owned  # again: still ours
    result = second.acquire()
    assert (result.owned, result.owner) == (False, os.getpid())
    first.release()
    first.release()
    assert second.acquire().owned
    assert path.read_text() == f"{os.getpid()}\n"
    second.release()
    assert isinstance(default_backend("linux"), type(default_backend()))


class FakeMsvcrt:
    """``msvcrt.locking`` of one process: a byte locked through one descriptor is busy for
    every other descriptor (Windows locks belong to a handle)."""

    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self) -> None:
        self.locked: dict[int, int] = {}
        self.calls: list[tuple[int, int, int, int]] = []

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        position = os.lseek(fd, 0, os.SEEK_CUR)
        self.calls.append((fd, mode, nbytes, position))
        if mode == self.LK_UNLCK:
            self.locked.pop(position, None)
            return
        holder = self.locked.get(position)
        if holder is not None and holder != fd:
            raise PermissionError(errno.EACCES, "Permission denied")
        self.locked[position] = fd


def test_windows_lock_with_a_mocked_msvcrt(tmp_path: Path) -> None:
    fake = FakeMsvcrt()
    path = tmp_path / LOCK_FILE
    first = StoreLock(path, MsvcrtBackend(fake))
    second = StoreLock(path, MsvcrtBackend(fake))
    assert first.acquire().owned
    result = second.acquire()
    assert (result.owned, result.owner) == (False, os.getpid())  # the pid stays readable
    assert all(position == WINDOWS_LOCK_OFFSET for _, _, _, position in fake.calls)
    assert all(nbytes == 1 for _, _, nbytes, _ in fake.calls)
    first.release()
    assert second.acquire().owned
    assert [mode for _, mode, _, _ in fake.calls] == [2, 2, 0, 2]
    second.release()


def test_windows_lock_errors(tmp_path: Path) -> None:
    class Broken(FakeMsvcrt):
        def locking(self, fd: int, mode: int, nbytes: int) -> None:
            if mode == self.LK_UNLCK:
                raise OSError(errno.EBADF, "Bad file descriptor")
            raise OSError(errno.EIO, "I/O error")

    lock = StoreLock(tmp_path / LOCK_FILE, MsvcrtBackend(Broken()))
    with pytest.raises(OSError, match="I/O"):
        lock.acquire()
    backend = MsvcrtBackend(Broken())
    fd = os.open(tmp_path / "x", os.O_RDWR | os.O_CREAT)
    try:
        backend.unlock(fd)  # an unlock error is ignored
    finally:
        os.close(fd)
