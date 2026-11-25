"""The queue store's migrations: files of older and newer Reframes, failed steps."""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from reframe.models import JobSettings, JobState, QueueJob, SourceRef
from reframe.queue import migrations, read_saved_queue
from reframe.queue.store import SCHEMA_VERSION, QueueStore, row_of

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)

#: The table of a Reframe without migrations (up to 0.10).
V1_TABLE = """
CREATE TABLE jobs (
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
V1_COLUMNS = (
    "id, position, state, settings_json, plan_json, issues_json, created_at, started_at, "
    "finished_at, output_path, log_path, error"
)


def job(job_id: str, **fields: Any) -> QueueJob:
    settings = JobSettings(source=SourceRef(path=Path("/media/a.mkv")))
    return QueueJob(id=job_id, position=0, settings=settings, created_at=NOW, **fields)


def run[T](store: QueueStore, call: Callable[[], T]) -> T:
    return store.submit(call).result()


def load(path: Path) -> tuple[QueueStore, list[QueueJob], list[str]]:
    store = QueueStore(path, now=lambda: NOW)
    loaded = run(store, store.load)
    return store, loaded.jobs, [w.code for w in loaded.warnings]


def columns(path: Path) -> list[str]:
    with contextlib.closing(sqlite3.connect(path)) as db:
        return [row[1] for row in db.execute("PRAGMA table_info(jobs)")]


def revision(path: Path) -> int:
    with contextlib.closing(sqlite3.connect(path)) as db:
        return migrations.revision(db)


def v1_file(path: Path) -> None:
    """A queue saved by Reframe 0.10: the table, ``user_version`` 1 and no revision."""
    db = sqlite3.connect(path)
    db.execute(V1_TABLE)
    db.execute("PRAGMA user_version = 1")
    db.execute(f"INSERT INTO jobs ({V1_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               old_writer_row("old"))  # fmt: skip
    db.commit()
    db.close()


def old_writer_row(job_id: str) -> tuple[object, ...]:
    """A row as Reframe 0.10 writes it: :func:`row_of` without the columns added since."""
    return row_of(job(job_id, state=JobState.DONE))[:12]


HEAD = len(migrations.STEPS)


def test_a_new_file_is_at_the_newest_revision(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    store, _, _ = load(path)
    run(store, lambda: store.upsert([row_of(job("a"))]))
    store.close()
    assert revision(path) == HEAD == 2
    assert columns(path)[-1] == "output_size"
    with contextlib.closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM store_revision").fetchone()[0] == 1


def test_a_file_of_reframe_0_10_is_migrated_and_keeps_its_jobs(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    v1_file(path)
    store, jobs, warnings = load(path)
    assert (warnings, [j.id for j in jobs], jobs[0].output_size) == ([], ["old"], None)
    store.close()
    assert revision(path) == HEAD
    assert "output_size" in columns(path)
    with contextlib.closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 1


def test_a_file_that_has_a_step_without_its_revision_is_migrated(tmp_path: Path) -> None:
    """The steps check what is there, so a column added before its revision is not added again."""
    path = tmp_path / "queue.sqlite3"
    v1_file(path)
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE jobs ADD COLUMN output_size INTEGER")
    store, jobs, warnings = load(path)
    assert (warnings, [j.id for j in jobs]) == ([], ["old"])
    store.close()
    assert revision(path) == HEAD


def test_a_current_file_is_not_written(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    store, _, _ = load(path)
    run(store, lambda: store.upsert([row_of(job("a"))]))
    store.close()
    with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as db:
        migrations.upgrade(db)
        assert db.total_changes == 0


def test_the_output_size_survives_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    store, _, _ = load(path)
    done = job("a", state=JobState.DONE, output_size=5_204_606_976)
    run(store, lambda: store.upsert([row_of(done)]))
    store.close()
    again, jobs, _ = load(path)
    assert [j.output_size for j in jobs] == [5_204_606_976]
    again.close()


def test_reframe_0_10_still_reads_and_writes_a_migrated_file(tmp_path: Path) -> None:
    """It names its columns, so the new column is NULL in the rows it writes."""
    path = tmp_path / "queue.sqlite3"
    store, _, _ = load(path)
    run(store, lambda: store.upsert([row_of(job("a", output_size=10))]))
    store.close()
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] <= 1  # it opens files up to 1
    assert db.execute(f"SELECT {V1_COLUMNS} FROM jobs").fetchall()
    db.execute(
        f"INSERT OR REPLACE INTO jobs ({V1_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        old_writer_row("a"),
    )
    db.commit()
    db.close()
    again, jobs, warnings = load(path)
    assert (warnings, [(j.id, j.output_size) for j in jobs]) == ([], [("a", None)])
    again.close()


def test_a_revision_of_a_newer_reframe_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    store, _, _ = load(path)
    run(store, lambda: store.upsert([row_of(job("a"))]))
    store.close()
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER")
        db.execute("UPDATE store_revision SET revision = 99")
    again, jobs, warnings = load(path)
    assert (warnings, [j.id for j in jobs]) == ([], ["a"])
    run(again, lambda: again.upsert([row_of(job("b", output_size=3))]))
    again.close()
    assert revision(path) == 99
    assert "priority" in columns(path)


def test_a_failed_step_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each step is one transaction with its revision, DDL included."""

    def fails(db: sqlite3.Connection) -> None:
        db.execute("ALTER TABLE jobs ADD COLUMN half_done INTEGER")
        db.execute("SELECT * FROM no_such_table")

    path = tmp_path / "queue.sqlite3"
    v1_file(path)
    monkeypatch.setattr(migrations, "STEPS", (*migrations.STEPS, fails))
    store, jobs, warnings = load(path)
    assert (jobs, warnings, store.read_only) == ([], ["queue.unreadable"], True)
    store.close()
    assert revision(path) == HEAD  # the steps before it are kept
    assert "half_done" not in columns(path)
    monkeypatch.undo()
    again, jobs, warnings = load(path)
    assert (warnings, [j.id for j in jobs]) == ([], ["old"])
    again.close()


def test_a_reader_without_the_lock_reads_a_file_of_reframe_0_10_as_it_is(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    v1_file(path)
    before = path.read_bytes()
    saved = read_saved_queue(tmp_path)
    assert (saved.problem, [(j.id, j.output_size) for j in saved.jobs]) == (None, [("old", None)])
    assert path.read_bytes() == before
