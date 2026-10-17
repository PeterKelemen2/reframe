# Test trim report: area M (models)

Files: `packages/reframe/tests/models/test_schema.py`, `test_roundtrip.py`, `test_models.py`.
Branch: `test-trim-M` (`test-trim/M` cannot exist next to the branch `test-trim`).

## Numbers

| | Before | After |
|---|---|---|
| Tests | 795 | 468 (-327, -41 %) |
| Wall time, with coverage | 47.0 s | 32.0 s, 53.2 s (two runs) |
| Wall time, back to back, no coverage | 39.0 s | 40.2 s |

The wall time did not go down. The time is in the kept Hypothesis round trips
(`test_model_round_trip`, 25 examples per model). The removed tests were cheap: one example
each, or no-op loops. The machine was under load (load average 26 from other agents), so the
timings vary by ±10 s.

The cut is larger than the expected 15-30 % because three parametrizations ran over every
public name with no effect for most of the names (no-op loops, a one-example copy of the
round trip, round trips of JSON scalars). The tests that hold real protection were not
touched.

## Coverage gate

```
before 25.061% 86/6918 branches 7135/21896 lines
after 25.061% 86/6918 branches 7135/21896 lines
TOTAL LOST: 0
```

All 203 JSON Schema snapshots are still checked.

## Deleted tests, by reason

### Subsumed by a property test in the same area
- `test_roundtrip.py::test_strategies_cover_every_model` (138 cases). It draws one example per
  model and checks `isinstance`. `test_model_round_trip[<model>]` draws 25 examples from the
  same `model_strategy(model)` and compares `again == instance`, and pydantic's `__eq__`
  also compares the class. Also, the health checks of the round trip are stricter.
- `test_models.py::test_job_draft_round_trips_and_rejects_unknown_fields`. The round trip is
  `test_model_round_trip[JobDraft]`. `extra="forbid"` is in the `JobDraft` snapshot
  (`additionalProperties: False`) and in `test_runtime_models_reject_unknown_fields` (the
  `ReframeModel` base).
- `test_models.py::test_field_change_round_trips_json_values`. The round trip is
  `test_model_round_trip[FieldChange]` (JsonValue fields). The default `kind="changed"` is in
  the snapshot.
- `test_models.py::test_plan_files_for_generated_chapters`. The round trip is
  `test_model_round_trip[EncodePlan]` / `[PlanFile]`, and `files` is in the `EncodePlan`
  snapshot.
- `test_models.py::test_subtitle_source_is_a_stream_or_a_file`. The `int | ExternalSubtitle`
  union is round-tripped by `test_model_round_trip[SubtitleOutputTrack]` (equality catches a
  wrong union branch).

### No-op parametrized cases
- `test_schema.py::test_definitions_match_their_own_schema`: 125 of 203 cases had no `$defs`,
  so the loop body never ran. The test now runs only over targets whose schema has `$defs`
  (78). The list is computed at collection, so a model that gets `$defs` later is included
  automatically.
- `test_roundtrip.py::test_alias_round_trip`: 51 plain `Literal` aliases and enums removed
  (65 -> 14). Their values are JSON strings or ints, so a round trip through pydantic cannot
  fail. Every one except `TemplateSection` is a field type of a public model and is
  round-tripped there. All of them are pinned by their own schema snapshot. Unions and
  `Annotated` aliases (Event, Range, JsonPatchOp, LanguageTag, NonNegativeInt, ...) are kept.
- `test_models.py::test_language_tags`: `pt-BR`, `sr-Latn`, `und` removed. The subtag regex
  `[A-Za-z0-9]{1,8}` has one path for them: `pt-BR` is the same as `zh-Hans`/`es-419`,
  `sr-Latn` is the same as `zh-Hans`, and `und` is the same as `hun`.
- `test_models.py::test_bad_language_tags`: `""` removed. `"e"` is the boundary just outside
  `{2,8}`.

### Tautology
- `test_schema.py::test_every_model_is_covered`. `TARGETS` is built from `models.__all__`
  with an `is_model` branch, so every BaseModel in `__all__` is always in it. The real check
  (every model defined in `reframe.models.*` is exported) is
  `test_roundtrip.py::test_every_public_name_is_exported`, which is kept.

### Duplicate
- `test_schema.py::test_event_schema_is_a_discriminated_union`. The mapping == `EVENT_TYPES`
  check is `test_models.py::test_event_types_match_the_union`. The discriminator
  `propertyName: type` is in the `Event` snapshot.

### "Model has field X" / pydantic behaviour that the snapshot pins
- `test_models.py::test_cover_art_is_not_a_video_track`: this only parses a dict that already
  has `cover_art`. The real rule (cover art is not a video track) is a C-3 probe rule and is
  tested in the probe tests. The `cover_art` field and `FieldOrder` values are in the snapshots.
- `test_models.py::test_template_defaults`: `crop_policy`, `chapter_name_policy`, `naming`
  and the size `mode` defaults are in the `JobTemplate` / size snapshots. `audio_rules == []`
  is a `default_factory=list`.
- `test_models.py::test_preset_needs_id_and_name`: `required: [id, name]`, `minLength: 1` and
  `category` default `"Custom"` are in the `Preset` snapshot.

## Mutation checks

Each mutation was applied to production code. Then the remaining tests of the area were run
(`-x`), and the mutation was reverted with `git checkout`. "No snapshots" means
`test_schema.py` was left out, to see which behaviour test catches the mutation.

| Mutation | Guards deleted | Killed by |
|---|---|---|
| `LanguageTag` primary `{2,8}` -> `{0,8}` | bad tag `""` | snapshot `AudioCodecRule`; no snapshots: `test_bad_language_tags[e]` |
| `LanguageTag` subtag separator `-` -> `[- ]` | (checked before `english language` was restored) | snapshot; no snapshots: `test_bad_language_tags[english language]` |
| Unexported model class added to `models/job.py` | `test_every_model_is_covered` | `test_every_public_name_is_exported` |
| `ResyncEvent` removed from the `Event` union | `test_event_schema_is_a_discriminated_union` | snapshot `Event`; no snapshots: `test_event_types_match_the_union` |
| `Preset.id` without `min_length=1` | `test_preset_needs_id_and_name` | snapshot `Preset` |
| `Preset.category` default `"Other"` | `test_preset_needs_id_and_name` | snapshot `Preset` |
| `JobTemplate.crop_policy` default `"fixed"` | `test_template_defaults` | snapshot `JobTemplate` |
| `JobDraft(DocumentModel)` (unknown fields allowed) | `test_job_draft_...` | snapshot `JobDraft` (survives with no snapshots) |
| `FieldChange.kind` default `"added"` | `test_field_change_...` | snapshot `FieldChange` |
| `EncodePlan.files` removed | `test_plan_files_...` | snapshot `EncodePlan` |
| `ExternalSubtitle.offset_ms` `ge=0` | `test_subtitle_source_...` | snapshot `ExternalSubtitle` |
| `MediaSource.cover_art` removed | `test_cover_art_...` | snapshot `MediaSource` |
| `Severity.INFO = "information"` | enum alias round trip | snapshot `Severity` (the deleted round trip passes with any value too) |
| Validator on `FieldChange.path` that the strategy does not satisfy | `test_strategies_cover_every_model` | `test_model_round_trip[FieldChange]` (no snapshots) |

After the checks, `git status` showed changes only in the three test files.

Restored after mutation analysis: `zh-Hans` (the only good tag with lower-case letters in a
subtag: a mutation `[A-Z0-9]` in subtags passes `es-419`/`de-CH-1996`) and
`"english language"` (the only bad tag with a space).

## Uncertain, kept
- `test_models.py::test_range_union`: mostly pydantic union behaviour. The
  `JobSettings.range` default `FullRange()` is a `default_factory` and is not in the snapshot.
- `test_models.py::test_filter_settings_keep_their_order`: dict order is pydantic and stdlib
  behaviour, but the filter chain order is a plan rule ("ordered map").
- `test_models.py::test_subtitle_defaults_differ_from_audio`: the defaults are constants, but
  the plan specifies them and the snapshot does not show them (`default_factory`).
- `test_models.py::test_runtime_models_reject_unknown_fields`: the snapshot also pins
  `additionalProperties: False`. Kept as the runtime check of the `ReframeModel` base.
- `test_models.py::test_move_op_alias`: the only test that pins `serialize_by_alias` (a round
  trip passes without it because `validate_by_name` is on).
- `test_models.py::test_audio_defaults_end_with_a_catch_all`: there is some overlap inside
  the test, but it tests our validator.
- All `test_json_schema_snapshot` (203), `test_model_round_trip` (138, the C-2 "Done when"),
  and the persistence/migration tests are kept unchanged.

## Unused fixtures
None. `tests/models/strategies.py` is still used in full.
