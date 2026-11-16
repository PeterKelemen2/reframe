# 0085 — Unused preset and facade members are removed

- Status: accepted
- Date: 2026-11-16
- Steps: Q-6.11 (finding X-07 of the simplification audit, with MOD-02 and SRV-03); C-9, S-2

## Context

Decision [0015](0015-presets-and-settings-stores.md) §2 says that duplicating a built-in preset
makes a user preset in the `Custom` category, and `PresetStore.duplicate` did that. Decisions
[0049](0049-s2-system-fs-settings-sources-preview.md) item 11 and
[0050](0050-s2-jobs-batch-presets-routes.md) item 10 list facade members that no route
exposes; the "Not exposed" table of `docs/plan/06-web-app.md` keeps them for later.

The simplification audit (decision [0083](0083-simplification-step-before-v1.md)) counted the
callers with `rg` over `packages/*/src`, `testing/`, `scripts/`, `frontend/src` and `desktop/`:
none outside the tests for these members:

- `PresetStore.rename`, `PresetStore.duplicate`, `PresetStore.default_id`, the `builtins=`
  argument of `PresetStore`;
- `PresetService.rename`, `PresetService.duplicate`, `PresetService.store`;
- `ToolsService.versions`, `ToolsService.discovering`, `SettingsService.path`,
  `SourceService.cache`;
- the test hooks `Reframe._load_settings`, `Reframe(settings=)`, `SettingsService(initial=)`,
  and the `timeout` argument of `ToolsService` (the facade always passes `tasks` and
  `data_dir`, so the `RuntimeError` of `ToolsService.fetch` could not happen).

The server renames a preset with `PUT /api/presets/{id}` and the frontend duplicates one itself
(`frontend/src/views/PresetsView.vue`: `GET`, then `POST /api/presets`, a built-in becomes
`Custom`). The CLI does neither.

## Decision

Remove these members. `ToolsService` takes `tasks` and `data_dir` as required arguments. Tests
that set settings write `settings.json` into the test's config folder.

0015 §2's duplicate rule is now a UI rule: the store has no `duplicate`, and the frontend keeps
the `Custom` category for a copy of a built-in. The store rules (a built-in cannot be changed,
names are unique) are unchanged and still tested through `save`, `create` and `delete`.

The "Not exposed" table of `docs/plan/06-web-app.md` loses the rows `settings.path`,
`tools.versions`, `presets.rename` and `presets.duplicate`; `tools.discovering`,
`sources.cache` and `presets.store` leave the two rows that list them with other members.

The same table also lost four rows in earlier simplification packages without a record of
their own (bookkeeping: the table's own rule says that a row whose member no longer exists
goes). They are listed here:

- `batch.definitions` (Q-6.6: `BatchService.definitions` was removed);
- `power.closed` and `power.countdown` (Q-6.7: `PowerService.closed` and `countdown` were
  removed);
- `jobs.detection_wait` (Q-6.9: `JobService.detection_wait` was removed).

## Consequences

- No user, HTTP, CLI or persisted change. The public core API is smaller.
- A future client that wants `duplicate` in the core must add it back with a caller.
- `packages/reframe-server/tests/test_facade_coverage.py` passes with the shorter table.

## Plan changes

- `docs/plan/06-web-app.md`, "Not exposed": the rows above.
- `docs/plan/05-core.md`, the `Reframe` sketch: `ToolsService` has no `versions`.
- Update notes in [0015](0015-presets-and-settings-stores.md) §2,
  [0049](0049-s2-system-fs-settings-sources-preview.md) item 11 and
  [0050](0050-s2-jobs-batch-presets-routes.md) item 10.
- `docs/status.md`, row C-9: the preset store has no `duplicate`.
