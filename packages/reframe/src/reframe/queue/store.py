"""The queue's SQLite store: ``<data dir>/queue.sqlite3`` (05 §C-11).

One table, the columns of the plan::

    jobs(id, position, state, settings_json, plan_json, issues_json, created_at, started_at,
         finished_at, output_path, log_path, error)

- **One writer.** Every call runs on one dedicated thread (:class:`QueueStore` owns it), in
  the order the queue made the calls. The queue keeps the jobs in memory; the store only
  persists them. A row is written whole (``INSERT OR REPLACE``) from values the caller
  serialised on the event loop, so a later write always carries the later state.
- **Atomic, crash-safe.** WAL journal, ``synchronous=FULL``; a change of several rows
  (positions) is one transaction. A crash loses nothing that was written.
- **Documents.** ``settings_json`` is a ``JobSettings`` document: it is migrated with
  ``load_document("job_settings", …)`` and keeps unknown fields (``DocumentModel``), which are
  written back unchanged. ``plan_json`` and ``issues_json`` are derived data: if they do not
  load (written by a newer Reframe), they are dropped from memory; the runner plans and
  validates again before a job runs.
- **A row that does not load** (a newer ``JobSettings`` schema, a state this Reframe does not
  know) stays in the file untouched and is left out of the queue; one ``app.warning``
  (``queue.rows_skipped``) says how many.
- **The file** (decision 0016): created at the first write, not at start-up. Its schema version
  is ``PRAGMA user_version``. A file of a newer Reframe is not read and never written
  (``queue.newer_version``: the queue starts empty for this session and is not saved). A
  corrupt file is renamed to ``queue.corrupt-<time>.sqlite3`` and a new one is started
  (``queue.corrupt``). A file that cannot be opened is left alone (``queue.unreadable``). A
  write that fails later (disk full) gives ``queue.not_saved`` once; the queue goes on in
  memory.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import logging
import os
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from reframe.models.events import AppWarningEvent
from reframe.models.issues import ValidationIssue
from reframe.models.job import JobSettings
from reframe.models.migrations import MigrationError, load_document
from reframe.models.plan import EncodePlan
from reframe.models.queue import JobState, QueueJob

__all__ = ["SCHEMA_VERSION", "STORE_FILE", "QueueStore", "Row", "StoreLoad", "row_of"]

log = logging.getLogger(__name__)

STORE_FILE = "queue.sqlite3"
#: ``PRAGMA user_version`` of the file this Reframe writes.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    position      INTEGER NOT NULL,
    state         TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    plan_json     TEXT,
    issues_json   TEXT NOT NULL DEFAULT '[]',
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    output_path   TEXT,
    log_path      TEXT,
    error         TEXT
)
"""
_COLUMNS = (
    "id",
    "position",
    "state",
    "settings_json",
    "plan_json",
    "issues_json",
    "created_at",
    "started_at",
    "finished_at",
    "output_path",
    "log_path",
    "error",
)
_ISSUES: TypeAdapter[list[ValidationIssue]] = TypeAdapter(list[ValidationIssue])

#: One row as SQLite values, in :data:`_COLUMNS` order.
Row = tuple[str, int, str, str, str | None, str, str, str | None, str | None, str | None,
            str | None, str | None]  # fmt: skip


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _path(value: Path | None) -> str | None:
    return None if value is None else str(value)


def row_of(job: QueueJob) -> Row:
    """The row of ``job`` (serialised on the caller's thread)."""
    return (
        job.id,
        job.position,
        job.state.value,
        job.settings.model_dump_json(),
        None if job.plan is None else job.plan.model_dump_json(),
        _ISSUES.dump_json(job.issues).decode("utf-8"),
        job.created_at.isoformat(),
        _time(job.started_at),
        _time(job.finished_at),
        _path(job.output_path),
        _path(job.log_path),
        job.error,
    )


def _job_of(values: Sequence[Any]) -> QueueJob:
    data = dict(zip(_COLUMNS, values, strict=True))
    settings = load_document("job_settings", json.loads(data["settings_json"]))
    assert isinstance(settings, JobSettings)
    plan: EncodePlan | None = None
    if data["plan_json"]:
        try:
            plan = EncodePlan.model_validate_json(data["plan_json"])
        except ValidationError:
            plan = None  # derived data of another version: planned again before a run
    try:
        issues = _ISSUES.validate_json(data["issues_json"] or "[]")
    except ValidationError:
        issues = []
    return QueueJob(
        id=data["id"],
        position=data["position"],
        state=JobState(data["state"]),
        settings=settings,
        plan=plan,
        issues=issues,
        created_at=data["created_at"],
        started_at=data["started_at"],
        finished_at=data["finished_at"],
        output_path=data["output_path"],
        log_path=data["log_path"],
        error=data["error"],
    )


@dataclass
class StoreLoad:
    """What :meth:`QueueStore.load` found."""

    jobs: list[QueueJob] = field(default_factory=list)
    warnings: list[AppWarningEvent] = field(default_factory=list)


class QueueStore:
    """The SQLite file, used from one worker thread (see the module doc).

    The public methods are coroutines-friendly: :meth:`submit` runs a call on the store's
    thread and returns a ``concurrent.futures.Future``; the queue awaits it with
    ``asyncio.wrap_future``. The blocking ``_…`` methods run on that thread only.
    """

    def __init__(self, path: Path, *, now: Callable[[], datetime]) -> None:
        self.path = path
        self._now = now
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="reframe-queue-store"
        )
        self._db: sqlite3.Connection | None = None
        self.read_only = False
        """The file is newer than this Reframe or cannot be opened: nothing is written."""
        self._failed = False
        self.warnings: list[AppWarningEvent] = []
        """Warnings of writes that failed (one per kind), to be published by the queue."""

    # ------------------------------------------------------------------ thread side

    def submit[T](self, call: Callable[[], T]) -> concurrent.futures.Future[T]:
        return self._executor.submit(call)

    def load(self) -> StoreLoad:
        """Read every job (runs on the store thread). Never raises for a bad file."""
        result = StoreLoad()
        if not self.path.exists():
            return result
        db: sqlite3.Connection | None = None
        try:
            db = self._connect(configure=False)  # nothing that writes before the version check
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                self.read_only = True
                result.warnings.append(
                    AppWarningEvent(
                        code="queue.newer_version",
                        message=(
                            "The queue was saved by a newer Reframe. It is not loaded and not "
                            "changed; jobs added now are not saved."
                        ),
                        detail=f"{self.path}: schema version {version}, this Reframe reads "
                        f"up to {SCHEMA_VERSION}",
                    )
                )
                return result
            self._configure(db)
            db.execute(_SCHEMA)
            if version == 0:  # an empty file of ours (the first write did not finish)
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            rows = db.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM jobs ORDER BY position, created_at"
            ).fetchall()
            self._db, db = db, None
        except sqlite3.DatabaseError as exc:
            _close(db)
            db = None
            return self._replace_corrupt(result, str(exc))
        except OSError as exc:
            self.read_only = True
            result.warnings.append(
                AppWarningEvent(
                    code="queue.unreadable",
                    message="The saved queue cannot be read; it is not changed this session.",
                    detail=f"{self.path}: {exc}",
                )
            )
            return result
        finally:
            _close(db)
        skipped: list[str] = []
        for values in rows:
            try:
                result.jobs.append(_job_of(values))
            except (ValueError, ValidationError, MigrationError, TypeError) as exc:
                skipped.append(f"{values[0]}: {exc}")
        if skipped:
            log.warning("queue rows skipped: %s", "; ".join(skipped))
            result.warnings.append(
                AppWarningEvent(
                    code="queue.rows_skipped",
                    message=(
                        f"{len(skipped)} saved queue job(s) could not be read (made by a newer "
                        "Reframe?). They stay in the file and are not shown."
                    ),
                    detail="; ".join(skipped),
                )
            )
        return result

    def upsert(self, rows: Sequence[Row]) -> None:
        """Write whole rows in one transaction (store thread)."""
        self._write(
            f"INSERT OR REPLACE INTO jobs ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(_COLUMNS))})",
            rows,
        )

    def delete(self, job_id: str) -> None:
        self._write("DELETE FROM jobs WHERE id = ?", [(job_id,)])

    def positions(self, pairs: Sequence[tuple[int, str]]) -> None:
        """Set ``position`` of each ``(position, id)`` in one transaction."""
        self._write("UPDATE jobs SET position = ? WHERE id = ?", pairs)

    def close(self) -> None:
        """Wait for the pending writes, then close the file (any thread but the store's)."""
        self._executor.submit(self._close_quietly).result()
        self._executor.shutdown(wait=True)

    # ------------------------------------------------------------------ internals

    def _connect(self, *, configure: bool = True) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        try:
            db.execute("PRAGMA busy_timeout = 5000")
            if configure:
                self._configure(db)
        except BaseException:
            db.close()
            raise
        return db

    @staticmethod
    def _configure(db: sqlite3.Connection) -> None:
        """WAL journal (it changes the file header, so only for a file of this version)."""
        mode = db.execute("PRAGMA journal_mode = WAL").fetchone()
        log.debug("queue store journal mode: %s", mode)
        db.execute("PRAGMA synchronous = FULL")

    def _open_for_write(self) -> sqlite3.Connection | None:
        if self.read_only:
            return None
        if self._db is None:
            db = self._connect()
            db.execute(_SCHEMA)
            db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._db = db
        return self._db

    def _write(self, sql: str, rows: Sequence[Sequence[object]]) -> None:
        try:
            db = self._open_for_write()
            if db is None:
                return
            with _transaction(db):
                db.executemany(sql, rows)
        except (sqlite3.Error, OSError) as exc:
            log.error("queue store write failed: %s", exc)
            if not self._failed:
                self._failed = True
                self.warnings.append(
                    AppWarningEvent(
                        code="queue.not_saved",
                        message="The queue could not be saved; changes are kept until Reframe "
                        "closes.",
                        detail=f"{self.path}: {exc}",
                    )
                )

    def _replace_corrupt(self, result: StoreLoad, detail: str) -> StoreLoad:
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"queue.corrupt-{stamp}.sqlite3")
        try:
            os.replace(self.path, backup)
            for suffix in ("-wal", "-shm"):
                side = self.path.with_name(self.path.name + suffix)
                if side.exists():
                    os.replace(side, backup.with_name(backup.name + suffix))
        except OSError as exc:
            self.read_only = True
            result.warnings.append(
                AppWarningEvent(
                    code="queue.unreadable",
                    message="The saved queue is damaged and could not be moved aside; it is "
                    "not changed this session.",
                    detail=f"{self.path}: {detail}; {exc}",
                )
            )
            return result
        result.warnings.append(
            AppWarningEvent(
                code="queue.corrupt",
                message=f"The saved queue was damaged. It was kept as {backup.name}; the "
                "queue starts empty.",
                detail=f"{self.path}: {detail}",
            )
        )
        return result

    def _close_quietly(self) -> None:
        db, self._db = self._db, None
        _close(db)


def _close(db: sqlite3.Connection | None) -> None:
    if db is not None:
        with contextlib.suppress(sqlite3.Error):
            db.close()


@contextlib.contextmanager
def _transaction(db: sqlite3.Connection) -> Iterator[None]:
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        with contextlib.suppress(sqlite3.Error):
            db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")
