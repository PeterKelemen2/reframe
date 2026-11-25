"""The queue store's Alembic migrations: files of older and newer Reframes, failed revisions."""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.script import ScriptDirectory

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


def revision(path: Path) -> str | None:
    with contextlib.closing(sqlite3.connect(path)) as db:
        row = db.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if row is None else str(row[0])


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


def head() -> str:
    script = ScriptDirectory.from_config(migrations.config())
    [only] = script.get_heads()
    return only


def test_the_revisions_form_one_line() -> None:
    script = ScriptDirectory.from_config(migrations.config())
    assert script.get_heads() == [head()]
    assert [s.revision for s in script.walk_revisions()] == ["0002", "0001"]


def test_a_new_file_is_at_the_newest_revision(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    store, _, _ = load(path)
    run(store, lambda: store.upsert([row_of(job("a"))]))
    store.close()
    assert revision(path) == head()
    assert columns(path)[-1] == "output_size"


def test_a_file_of_reframe_0_10_is_migrated_and_keeps_its_jobs(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    v1_file(path)
    store, jobs, warnings = load(path)
    assert (warnings, [j.id for j in jobs], jobs[0].output_size) == ([], ["old"], None)
    store.close()
    assert revision(path) == head()
    assert "output_size" in columns(path)
    with contextlib.closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 1


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
        db.execute("UPDATE alembic_version SET version_num = '9999'")
    again, jobs, warnings = load(path)
    assert (warnings, [j.id for j in jobs]) == ([], ["a"])
    run(again, lambda: again.upsert([row_of(job("b", output_size=3))]))
    again.close()
    assert revision(path) == "9999"
    assert "priority" in columns(path)


def test_a_failed_revision_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each revision is one transaction with its version stamp, DDL included."""
    scripts = tmp_path / "migrations"
    shutil.copytree(migrations.SCRIPTS, scripts, ignore=shutil.ignore_patterns("__pycache__"))
    (scripts / "versions" / "r0003_fails.py").write_text(
        '"""Adds a column, then fails."""\n'
        "import sqlalchemy as sa\n"
        "from alembic import op\n\n"
        'revision = "0003"\n'
        'down_revision = "0002"\n'
        "branch_labels = depends_on = None\n\n\n"
        "def upgrade():\n"
        '    op.add_column("jobs", sa.Column("half_done", sa.Integer()))\n'
        '    op.execute("SELECT * FROM no_such_table")\n\n\n'
        "def downgrade():\n"
        "    pass\n"
    )
    path = tmp_path / "queue.sqlite3"
    v1_file(path)
    monkeypatch.setattr(migrations, "SCRIPTS", scripts)
    store, jobs, warnings = load(path)
    assert (jobs, warnings, store.read_only) == ([], ["queue.unreadable"], True)
    store.close()
    assert revision(path) == "0002"  # the revisions before it are kept
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
