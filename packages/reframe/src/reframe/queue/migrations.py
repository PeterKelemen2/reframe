"""Migrations of the queue store's tables.

A file's revision is the number of :data:`STEPS` applied to it, kept in ``store_revision``.
``PRAGMA user_version`` (:data:`reframe.queue.store.SCHEMA_VERSION`) marks a file that an older
Reframe must not open: a step only adds what an older Reframe can ignore, such as a column that
may be NULL; anything else also raises ``user_version``.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Callable

__all__ = ["STEPS", "MigrationFailedError", "revision", "upgrade"]


class MigrationFailedError(Exception):
    """The tables could not be brought up to date. Steps before the failed one are kept."""


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _jobs_table(db: sqlite3.Connection) -> None:
    # A file of a Reframe without migrations has this table and no revision.
    db.execute(
        """
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
    )


def _job_output_size(db: sqlite3.Connection) -> None:
    if "output_size" not in _columns(db, "jobs"):
        db.execute("ALTER TABLE jobs ADD COLUMN output_size INTEGER")


STEPS: tuple[Callable[[sqlite3.Connection], None], ...] = (_jobs_table, _job_output_size)
"""Revision ``n`` is the first ``n`` steps. Append only: never change or reorder a step."""


def revision(db: sqlite3.Connection) -> int:
    """The revision of the file of ``db``; 0 for a file without one."""
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'store_revision'"
    ).fetchone():
        return 0
    row = db.execute("SELECT revision FROM store_revision").fetchone()
    return 0 if row is None else int(row[0])


def upgrade(db: sqlite3.Connection) -> None:
    """Apply the steps that the file of ``db`` lacks (blocking; ``db`` in autocommit mode).

    Each step commits on its own, with its revision. A file at a revision this Reframe does
    not know (a newer Reframe wrote it) is left as it is.

    :raises MigrationFailedError: a step failed; the file keeps the steps before it.
    """
    while (current := revision(db)) < len(STEPS):
        try:
            db.execute("BEGIN IMMEDIATE")
            current = revision(db)  # again under the write lock
            if current < len(STEPS):
                STEPS[current](db)
                db.execute("CREATE TABLE IF NOT EXISTS store_revision (revision INTEGER NOT NULL)")
                db.execute("DELETE FROM store_revision")
                db.execute("INSERT INTO store_revision VALUES (?)", (current + 1,))
            db.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                db.execute("ROLLBACK")
            raise MigrationFailedError(f"revision {current + 1}: {exc}") from exc
