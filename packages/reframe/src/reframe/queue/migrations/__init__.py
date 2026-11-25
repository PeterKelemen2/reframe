"""Alembic migrations of the queue store's tables.

``PRAGMA user_version`` (:data:`reframe.queue.store.SCHEMA_VERSION`) marks a file that an older
Reframe must not open. A revision only adds what an older Reframe can ignore, such as a column
that may be NULL; anything else also raises ``user_version``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alembic.config import Config

__all__ = ["HEAD", "SCRIPTS", "MigrationFailedError", "config", "is_current", "upgrade"]

SCRIPTS = Path(__file__).parent
HEAD = "0002"
"""The newest revision in :data:`SCRIPTS`."""


class MigrationFailedError(Exception):
    """The tables could not be brought up to date; the file is as it was."""


def is_current(db: sqlite3.Connection) -> bool:
    """Whether the file of ``db`` is at :data:`HEAD`. Reads two small tables, so a store can
    skip :func:`upgrade`, which imports Alembic and SQLAlchemy (about 130 ms)."""
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
    ).fetchone():
        return False
    return [row[0] for row in db.execute("SELECT version_num FROM alembic_version")] == [HEAD]


def config() -> Config:
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(SCRIPTS))
    return cfg


def upgrade(path: Path) -> None:
    """Bring the SQLite file at ``path`` to the newest revision (blocking).

    Each revision commits on its own, with its version stamp. A file at a revision this
    Reframe does not know (a newer Reframe wrote it) is left as it is.
    """
    import sqlalchemy
    from alembic import command
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from alembic.util import CommandError
    from sqlalchemy.pool import NullPool

    cfg = config()
    engine = sqlalchemy.create_engine(
        sqlalchemy.URL.create("sqlite", database=str(path)),
        poolclass=NullPool,
        # The sqlite3 module's legacy mode commits DDL at once: a crash would leave a column
        # added without its revision.
        connect_args={"autocommit": False, "timeout": 5.0},
    )
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_heads()
            connection.rollback()
            known = {
                script.revision for script in ScriptDirectory.from_config(cfg).walk_revisions()
            }
            if not set(current) <= known:
                return
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
    except (sqlalchemy.exc.SQLAlchemyError, CommandError) as exc:
        raise MigrationFailedError(str(exc)) from exc
    finally:
        engine.dispose()
