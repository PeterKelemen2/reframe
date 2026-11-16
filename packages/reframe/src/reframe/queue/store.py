"""The queue's SQLite store, ``<data dir>/queue.sqlite3``.

- **One writer.** Every call runs on one dedicated thread (:class:`QueueStore` owns it), in
  the order the queue made the calls. A row is written whole (``INSERT OR REPLACE``) from
  values serialised on the caller's thread, so a later write carries the later state.
- **Atomic.** Each call is one transaction. The file uses WAL and ``synchronous=FULL``, so a
  crash loses no committed write.
- **Exact values.** Text round-trips exactly, lone surrogates included (a file name that is
  not UTF-8): JSON is ASCII, and a text column with a surrogate is stored as a BLOB.
- **Documents.** ``settings_json`` is migrated on load and keeps unknown fields
  (``DocumentModel``), which are written back unchanged. ``plan_json`` and ``issues_json``
  are derived data: when they do not load, the runner plans and validates again before a run.
- **A row that does not load** (a newer schema, an unknown state, or a document nested more
  than :data:`~reframe.settings.MAX_DEPTH` levels) stays in the file untouched and is left
  out of the queue. Such a document is damage, never a crash, and is never written
  (:func:`row_of`).
- **The file** is created at the first write, not at start-up. A file of a newer Reframe is
  never written. Only the process that holds the owner lock writes it; another process keeps
  its jobs in memory only (:attr:`QueueStore.read_only`).
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import functools
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
from reframe.models.text import json_text
from reframe.settings import TOO_DEEP, too_deep

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
Row = tuple[str, int, str, str, str | None, str, str, str | None, str | None,
            str | bytes | None, str | bytes | None, str | bytes | None]  # fmt: skip


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


class _Refused(str):
    """The value of a JSON column that is not written (see :func:`row_of`); the text says why.
    A ``str``, so a :data:`Row` keeps its type."""

    __slots__ = ()


class _TooDeep(ValueError):
    """A JSON column of a row nested more than ``MAX_DEPTH`` levels deep (a damaged row)."""


def _json(data: Any) -> str:
    return json_text(data, separators=(",", ":"))


def _text(value: str | None) -> str | bytes | None:
    """A text column: the string, or, when it holds lone surrogates (SQLite text must be
    UTF-8), its exact code units as a BLOB (UTF-8 with ``surrogatepass``)."""
    if value is None:
        return None
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return value.encode("utf-8", "surrogatepass")
    return value


def _untext(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", "surrogatepass")
    return str(value)


def _unpath(value: object) -> Path | None:
    text = _untext(value)
    return None if text is None else Path(text)


def _path(value: Path | None) -> str | bytes | None:
    return None if value is None else _text(str(value))


def _document(column: str, dump: Callable[[], Any]) -> str:
    """The JSON text of a document column, or a :class:`_Refused` value when it is nested too
    deep. Never raises."""
    try:
        data = dump()
    except (ValueError, TypeError, RecursionError) as exc:  # Pydantic's model_dump: too deep
        return _Refused(f"{column}: {exc}")
    if too_deep(data):
        return _Refused(f"{column}: {TOO_DEEP}")
    return _json(data)


def row_of(job: QueueJob) -> Row:
    """The row of ``job``, serialised on the caller's thread. A settings, plan or issues
    document nested too deep is not serialised: its column holds a marker, and
    :meth:`QueueStore.upsert` does not write the row. Never raises for such a document."""
    plan = job.plan
    return (
        job.id,
        job.position,
        job.state.value,
        _document("settings_json", functools.partial(job.settings.model_dump, mode="json")),
        None
        if plan is None
        else _document("plan_json", functools.partial(plan.model_dump, mode="json")),
        _document("issues_json", functools.partial(_ISSUES.dump_python, job.issues, mode="json")),
        job.created_at.isoformat(),
        _time(job.started_at),
        _time(job.finished_at),
        _path(job.output_path),
        _path(job.log_path),
        _text(job.error),
    )


def _refused(row: Sequence[object]) -> str | None:
    """Why ``row`` (of :func:`row_of`) is not written, or ``None``."""
    reasons = [value for value in row if isinstance(value, _Refused)]
    return "; ".join(reasons) if reasons else None


def _parse(column: str, value: object, default: str) -> Any:
    """Raises :class:`_TooDeep` for a document nested too deep, whatever depth the parser
    itself would manage, and ``ValueError`` for text that is not JSON."""
    try:
        data = json.loads(_untext(value) or default)
    except RecursionError:  # CPython's C-stack check, far beyond MAX_DEPTH
        raise _TooDeep(f"{column}: {TOO_DEEP}") from None
    if too_deep(data):
        raise _TooDeep(f"{column}: {TOO_DEEP}")
    return data


def _derived(column: str, value: object, default: str) -> tuple[bool, Any]:
    """A derived column that is not JSON is dropped (``(False, None)``); a too-deep one raises
    :class:`_TooDeep`."""
    try:
        return True, _parse(column, value, default)
    except _TooDeep:
        raise
    except ValueError:
        return False, None


def _job_of(values: Sequence[Any]) -> QueueJob:
    data = dict(zip(_COLUMNS, values, strict=True))
    # Every document is checked before any is loaded: one nested too deeply damages the row.
    settings_data = _parse("settings_json", data["settings_json"], "")
    plan_ok, plan_data = _derived("plan_json", data["plan_json"], "")  # NULL: not JSON
    issues_ok, issues_data = _derived("issues_json", data["issues_json"], "[]")
    if not isinstance(settings_data, dict):
        raise ValueError("settings_json: not a JSON object")
    settings = load_document("job_settings", settings_data)
    assert isinstance(settings, JobSettings)
    plan: EncodePlan | None = None
    if plan_ok:
        try:
            plan = EncodePlan.model_validate(plan_data)
        except ValidationError:
            plan = None  # derived data of another version: planned again before a run
    issues: list[ValidationIssue] = []
    if issues_ok:
        try:
            issues = _ISSUES.validate_python(issues_data)
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
        output_path=_unpath(data["output_path"]),
        log_path=_unpath(data["log_path"]),
        error=_untext(data["error"]),
    )


@dataclass
class StoreLoad:
    """What :meth:`QueueStore.load` found."""

    jobs: list[QueueJob] = field(default_factory=list)
    warnings: list[AppWarningEvent] = field(default_factory=list)


class QueueStore:
    """The SQLite file, used from one worker thread.

    :meth:`submit` runs a call on that thread and returns a ``concurrent.futures.Future``,
    which the queue awaits with ``asyncio.wrap_future``. The ``_…`` methods run on that
    thread only.
    """

    def __init__(self, path: Path, *, now: Callable[[], datetime]) -> None:
        self.path = path
        self._now = now
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="reframe-queue-store"
        )
        self._db: sqlite3.Connection | None = None
        self.read_only = False
        """Nothing is written: the file is newer than this Reframe, cannot be opened, or
        another process owns it."""
        self._failed = False
        self._refused: set[str] = set()
        """Jobs whose ``queue.job_not_saved`` warning was given."""
        self.warnings: list[AppWarningEvent] = []
        """Warnings of writes that failed (one per kind), to be published by the queue."""

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
            except (ValueError, ValidationError, MigrationError, TypeError, RecursionError) as exc:
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
        """Write whole rows in one transaction (store thread).

        A row that :func:`row_of` marked is left out, so the file keeps that job's row as it
        was. One ``queue.job_not_saved`` warning per job."""
        kept: list[Row] = []
        for row in rows:
            reason = _refused(row)
            if reason is None:
                kept.append(row)
                continue
            log.error("queue job %s not saved: %s", row[0], reason)
            if row[0] not in self._refused and not self.read_only:
                self._refused.add(row[0])
                self.warnings.append(
                    AppWarningEvent(
                        code="queue.job_not_saved",
                        message=f"The queue job {row[0]} could not be saved: its data is "
                        "nested too deeply. It stays in the queue until Reframe closes.",
                        detail=reason,
                    )
                )
        if not kept:
            return
        rows = kept
        self._write(
            f"INSERT OR REPLACE INTO jobs ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(_COLUMNS))})",
            rows,
        )

    def delete(self, job_id: str) -> None:
        self._write("DELETE FROM jobs WHERE id = ?", [(job_id,)])

    def close(self) -> None:
        """Wait for the pending writes, then close the file (any thread but the store's)."""
        self._executor.submit(self._close_quietly).result()
        self._executor.shutdown(wait=True)

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
        """WAL journal. Only for a file of this version: the change rewrites its header."""
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
