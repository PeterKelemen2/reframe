"""What a front end uses of the queue: the :class:`QueueLike` protocol, which the in-process
:class:`~reframe.queue.QueueService` and ``reframe.remote.RemoteQueue`` both implement, and the
saved queue read without owning it (no lock, no restore, nothing written to the store)."""

from __future__ import annotations

import builtins
import contextlib
import os
import sqlite3
import urllib.parse
from collections.abc import Sequence
from pathlib import Path, PurePath
from typing import Protocol

from pydantic import ValidationError

from reframe.models.job import JobSettings
from reframe.models.migrations import MigrationError
from reframe.models.queue import QueueJob
from reframe.queue.store import _COLUMNS, SCHEMA_VERSION, STORE_FILE, _job_of

__all__ = ["QueueLike", "SavedQueue", "read_saved_queue"]

_Jobs = builtins.list[QueueJob]


class QueueLike(Protocol):
    """The queue calls of a front end. An unknown job id raises
    :class:`~reframe.queue.UnknownJobError`; a call that the job's state refuses raises
    :class:`~reframe.queue.JobStateError`."""

    async def add(self, job: JobSettings, *, position: int | None = None) -> QueueJob: ...

    def list(self) -> _Jobs: ...

    def get(self, job_id: str) -> QueueJob | None: ...

    def start(self, *, job_ids: Sequence[str] | None = None) -> None: ...

    async def wait(self, job_ids: Sequence[str] | None = None) -> _Jobs: ...

    async def cancel(self, job_id: str | None = None) -> None: ...

    async def pause(self, job_id: str | None = None) -> None: ...

    async def resume(self, job_id: str | None = None) -> None: ...

    async def retry(self, job_id: str) -> QueueJob: ...

    async def remove(self, job_id: str) -> None: ...

    async def reorder(self, job_ids: Sequence[str]) -> None: ...

    def log_path(self, job_id: str) -> Path: ...


class SavedQueue:
    """The jobs of a saved queue, as the file holds them: a job that was running when its
    owner stopped still says ``running``."""

    def __init__(self, jobs: _Jobs, problem: str | None = None) -> None:
        self.jobs = jobs
        self.problem = problem
        """Why the file, or some of its rows, could not be read, or why it may miss its newest
        changes."""


def _store_uri(path: PurePath) -> str:
    """``path`` as an SQLite ``file:`` URI. SQLite refuses a host in a URI, so a UNC path keeps
    both its slashes in the URI's path: ``\\\\nas\\share\\q`` is ``file:////nas/share/q``."""
    text = path.as_posix()
    if not text.startswith("/"):
        text = "/" + text  # a drive letter: file:///C:/…
    return "file://" + urllib.parse.quote_from_bytes(os.fsencode(text), safe="/:")


def read_saved_queue(data_dir: Path) -> SavedQueue:
    """Read ``<data dir>/queue.sqlite3`` without the queue's lock. Blocking. Never raises.

    Read-only mode still makes the WAL side files. Where it cannot (no ``-shm`` file in a folder
    the user cannot write), the file is read as immutable: the commits in its ``-wal`` file
    since the last checkpoint are then not seen, and ``problem`` says that they may be missing."""
    path = data_dir / STORE_FILE
    if not path.exists():
        return SavedQueue([])
    rows: builtins.list[tuple[object, ...]] = []
    problem: str | None = None
    uri = _store_uri(path.absolute())
    for options in ("mode=ro", "mode=ro&immutable=1"):
        try:
            db = sqlite3.connect(f"{uri}?{options}", uri=True)
            try:
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                if version > SCHEMA_VERSION:
                    return SavedQueue([], f"{path}: saved by a newer Reframe (schema {version})")
                rows = db.execute(
                    f"SELECT {', '.join(_COLUMNS)} FROM jobs ORDER BY position, created_at"
                ).fetchall()
            finally:
                db.close()
        except sqlite3.Error as exc:
            problem = f"{path}: {exc}"
            continue
        if problem is not None:  # read as immutable
            problem = _missed_wal(path, problem)
        break
    jobs: _Jobs = []
    skipped = 0
    for values in rows:
        try:
            jobs.append(_job_of(values))
        except (ValueError, ValidationError, MigrationError, TypeError, RecursionError):
            skipped += 1
    if skipped and problem is None:
        problem = f"{skipped} saved job(s) could not be read (made by a newer Reframe?)"
    return SavedQueue(jobs, problem)


def _missed_wal(path: Path, why: str) -> str | None:
    """The problem of a store read as immutable, ``None`` when it has no ``-wal`` file to miss."""
    wal = path.with_name(f"{path.name}-wal")
    size = 0
    with contextlib.suppress(OSError):
        size = wal.stat().st_size
    if not size:
        return None
    return f"{why}; shown as of its last checkpoint, so newer changes in {wal.name} may be missing"
