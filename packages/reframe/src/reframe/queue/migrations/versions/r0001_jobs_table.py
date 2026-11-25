"""The jobs table.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A file of a Reframe without these migrations has this table and no revision.
    op.execute(
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


def downgrade() -> None:
    op.drop_table("jobs")
