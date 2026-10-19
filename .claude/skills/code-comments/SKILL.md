---
name: code-comments
description: How to write comments and docstrings in Reframe code (Python, TypeScript, Vue), and how to trim existing ones without changing code. Use it before you write or change code in this repository, when a code change makes a nearby comment wrong, and when asked to clean up, trim or audit comments or docstrings (/code-comments [paths]).
argument-hint: "[paths to clean up]"
---

# Comments and docstrings

Each comment costs tokens every time an agent reads the file, and work every time the code
near it changes. Write few comments, and only ones that stay true while their code stays the
same. Older code in this repository has more comments than these rules allow: do not copy its
density.

## Before you write a comment

Ask: without this comment, would a capable reader misread the code, or "fix" it into a bug?
If not, write no comment. Most functions need none.

A comment that passes:

- says **why**: a tool or OS quirk, a race, an invariant that the next change could break, the
  reason for code that looks wrong or too complex;
- is about **the code next to it** only. A comment about another module goes stale when that
  module changes, because the person who changes it never sees the comment. Put a contract
  between modules in a test, or in the docstring of the code that owns it;
- has one or two lines, in the present tense.

Docstrings: a public name gets a one-line docstring when its name and types do not say enough.
Add lines only for what the signature cannot show: edge-case results, "never raises", side
effects, the thread or event loop it must run on. A module docstring is one paragraph: what the
module is for and its main invariant. Private helpers and well-named tests get none.

## Never write

| Not in code | Put it here |
|---|---|
| Step IDs, plan sections, milestones: `(C-6)`, `05 §C-9`, `04 §Track rules`, `M3` | The commit message |
| Review and issue IDs: `(RB-3)` | The commit message |
| History: "now", "no longer", "was", "new", "follow-up", "fixed", "changed to" | The commit message or a decision record |
| Lists that copy the code: test names, callers, fields, enum values, supported tags | Nowhere: `grep` finds them |
| Counts, tool versions, dates: "438 codes", "FFmpeg n9.0.2" | The test that checks them |
| Tool behaviour, past the one line that names what the code works around | A test, and "Verified tool behaviour" in `testdata/README.md` |
| What the code does step by step; parameter lists that repeat the signature | Nowhere |
| Which test proves which "Done when" line | Test names that state the behaviour |
| Design text: how a feature works across modules | The plan or a decision record |
| New divider comments (`# ------ public`) | Nowhere |

Decision numbers: give the reason in a few words instead. Only when the reason does not fit in
two lines may an inline `#` comment point to the record (`# See decision 0034.`). Never put a
decision number in a docstring.

## Comments that are code

- **Pragmas**: `# noqa: …`, `# type: ignore[…]`, `# pragma: no cover`, `# fmt: skip`,
  `// oxlint-disable…`, `@ts-expect-error`. You may cut the explanation after a pragma. Never
  remove the pragma itself as part of a comment change.
- **Docstrings that the program reads.** They are documentation for other people, so apply the
  rules above to them more strictly. But a change to them changes output:
  - Pydantic models (`use_attribute_docstrings=True`): the model docstring and the docstring
    under each field become the JSON Schema `description`, then OpenAPI, then the frontend's
    generated TypeScript types. Write them for a frontend developer: what the value means, its
    unit and its range. `packages/reframe/tests/models/__snapshots__/test_schema.ambr` records them.
  - typer commands (`reframe.cli`) and FastAPI routes: the docstring is `--help` text or the
    OpenAPI description.
  - `__doc__`: some modules pass it to `argparse` and some tests read it (`grep -rn __doc__`).

## When you change code

- Read the comments on the lines you change, and the docstring of each function you change. If
  one is now wrong, delete it or cut it to what is still true. Do not add text to describe
  the change.
- Do not search other files for comments that mention what you changed.
- If you see a wrong comment, delete it. Do not rewrite it.

## Clean-up run

Input: the paths in the arguments. With no paths, use the Python, TypeScript and Vue files that
this branch changed (`git diff --name-only main...HEAD`).

1. Take one file at a time. Keep, cut or delete each comment and docstring by the rules above.
   Remove step IDs, plan sections and review IDs without looking them up: the reason is never
   in the reference itself.
2. Before you delete a fact that the code does not show (a tool quirk, a reason), find where
   it is recorded: a test, `testdata/README.md`, the plan or a decision record (`grep` for a
   key word). If it is not recorded, keep it as one line, or move it there in the same commit.
   Never delete the only record of verified tool behaviour.
3. Change only comments and docstrings. Make no renames, format changes or code fixes, not even
   obvious ones. List them for the user instead.
4. Check:

   ```sh
   uv run python .claude/skills/code-comments/scripts/comments_only.py   # add --base main for commits
   uv run ruff format && uv run ruff check
   ```

   `comments_only.py` compares each changed Python file with git. Once docstrings are removed,
   the code must be the same, and each pragma must stay on its line. If the check passes, the
   files differ only in docstrings and comments, so mypy and the full test suite are not needed.
   If it lists docstrings that the program reads, run the tests that see them (about 1 minute):

   ```sh
   uv run pytest -q packages/reframe/tests/models packages/reframe/tests/definitions packages/reframe/tests/test_cli.py packages/reframe-server/tests
   ```

   A changed model description makes the schema snapshot fail. Run that test file again with
   `--snapshot-update`, then read the `.ambr` diff: only `description` lines may change.

   Frontend: in `frontend/`, run `npm run lint && npm run fmt:check && npm run typecheck`.
5. For a large scope (a package or more), split the work by directory. Give each agent its own
   files, and tell it to do step 4 before it reports.

## Examples from this repository

```python
# Before
"""Run ``job`` (see the module doc). Never raises for an expected failure."""
# The plan's output is the source: there is no .part file or plan file to clean up
# (decision 0034), so the queue gets no plan to clean up after.
outcome.plan = None

# After
"""Run ``job``. Never raises for an expected failure."""
# A metadata edit writes into the source: the queue has nothing to clean up.
outcome.plan = None
```

```python
# A process that exited 0 just as the cancel came is not "stopped" (RB-3).    before
# A process that exited 0 just as the cancel came is not "stopped".           after
```

```python
"""Files that share a fingerprint at ``level`` (04 §Grouping)."""     # before: a schema description
"""Files that share a fingerprint at ``level``."""                    # after
```

```python
# Before: a test module docstring
"""C-9 settings store: ``<config>/settings.json`` with migrations, atomic writes and the
damaged / newer / unreadable file handling.

"Done when" (05 §C-9) parts proved here: an old-schema settings file loads after migration
(:func:`test_old_schema_fixture_loads_after_migration`, ...
"""

# After
"""The settings store: migrations, atomic writes, damaged, newer and unreadable files."""
```
