# 0108 — Our own migration runner for the queue store, in place of Alembic

- Status: accepted
- Date: 2026-11-25
- Steps: C-11

## Context

Decision 0107 put the queue store's tables under Alembic. The store uses Alembic only as a
migration runner: it has one table, raw `sqlite3` with whole-row writes, and no ORM. The
Pydantic models in `reframe.models` are the only schema (CLAUDE.md), and the store relies on
things an ORM works against: text with lone surrogates stored as BLOBs, rows that do not load
kept untouched, rows nested too deeply never written.

What Alembic cost, measured on Linux:

- four packages (`alembic`, `sqlalchemy`, `mako`, `markupsafe`); SQLAlchemy is 8.8 MB of the
  51 MB frozen sidecar, before its Python modules;
- about 130 ms of `import reframe` until its imports were moved into the migration path, and
  then a hand-kept `HEAD` constant to keep them there;
- a second connection to the file, `autocommit=False` so that DDL is in a transaction, and a
  PyInstaller rule for the revision files.

What it gave that the store uses: ordered steps with a version stamp, each step in one
transaction. Branches, merges, downgrades and autogenerate are not used. SQLite runs DDL inside
an explicit transaction, and `ALTER TABLE` adds, renames and drops columns.

## Decision

- `reframe/queue/migrations.py`: `STEPS` is an append-only tuple of functions; revision `n` is
  the first `n` steps, kept in a one-row table `store_revision`. `upgrade(db)` runs on the
  store's own connection: each missing step in `BEGIN IMMEDIATE … COMMIT` with its revision,
  so a step that fails leaves the file at the revision before it. A current file costs one
  small read and no write. A revision higher than `len(STEPS)` (a newer Reframe) is left as
  it is.
- A step checks what is there where that is cheap (`ADD COLUMN` only when the column is
  missing), so a file that has a step's change without its revision opens.
- Unchanged from 0107: `PRAGMA user_version` stays the compatibility line (1), a step only adds
  what an older Reframe can ignore, a failed migration makes the store read-only with
  `queue.unreadable`, and readers without the owner lock do not migrate (`select_jobs`).
- Removed: the `alembic` and `sqlalchemy` dependencies, `[tool.alembic]`, the sidecar spec's
  rule for the revision files. `uv.lock` is as it was before 0107.

## Consequences

- A new step: append a function to `STEPS` and a test with a file of the revision before it
  to `test_store_migrations.py`. A step that an older Reframe cannot ignore also raises
  `SCHEMA_VERSION`.
- A change that `ALTER TABLE` cannot make (a column's type or constraint) needs SQLite's table
  rebuild written by hand in its step. Such a change also breaks older versions, so it comes
  with a `user_version` bump.
- No Reframe release had Alembic, so no saved queue has an `alembic_version` table to adopt.

## Plan changes

- `05-core.md` §C-11: the store's migrations.
- [0107](0107-queue-store-migrations-with-alembic.md): its Alembic part is superseded.
