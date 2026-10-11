# 0004 — Shared test infrastructure in `testing/`

- Status: accepted
- Date: 2026-10-11
- Steps: C-0, Q-2.1

## Context

The plan (02 §Repository layout) has `scripts/` for dev helpers and `testdata/` for fixtures,
and every package keeps its tests in `packages/<name>/tests/`. The fake FFmpeg and the fixture
helpers (Q-2.1) are used by the core tests (C-1, C-4, C-11), the server tests (S-2) and the
end-to-end tests (F-17). If they lived in `packages/reframe/tests/`, the server tests could not
import them cleanly (pytest runs with `--import-mode=importlib`, and a test folder is not a
package).

## Decision

Shared test infrastructure lives in a top-level `testing/` folder as the importable package
`reframe_testing`. It is on pytest's `pythonpath` and mypy's `mypy_path`, and is checked by
ruff and strict mypy like the rest of the code. Its own tests are in `testing/tests/`. A pytest
plugin (`reframe_testing.pytest_plugin`) provides the `fixture_media` and `fake_tools`
fixtures to every test suite. It is never shipped (not part of any wheel).

`scripts/make-testdata.py` stays the entry point named by the plan. It is a thin wrapper over
`reframe_testing.media`.

## Consequences

- Server and end-to-end tests reuse the same fake FFmpeg and fixtures with no copies.
- One more top-level folder.

## Plan changes

- `docs/plan/02-architecture.md` §Repository layout: added `testing/`.
