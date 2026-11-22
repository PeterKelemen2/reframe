# 0090 — A smaller batch API and one draft path

- Status: accepted
- Date: 2026-11-16
- Steps: Q-6.15 (amends [0040](0040-batch-engine-and-reframe-batch.md) §8 and R1-4, and
  [0031](0031-audio-and-subtitle-selection-stage.md) §6)

## Context

The simplification audit ([docs/simplify/](../simplify/plan.md), package Q-6.15) found five
places where the batch engine and the draft path carry more API than their callers use:

- **X-03** (CLI-03, QJ-03): in client mode, `cli.OwnerJobs.draft` was a second copy of
  `JobService.draft` (probe, preset, naming options, `draft_from_preset`, naming, the track-issue
  filter, `JobDraft`). Only the validation step was different: the queue's owner validates
  ([0061](0061-c17-remote-queue-and-queue-commands.md) item 4).
- **BAT-03**: `reframe.batch.draft_tracks` (a wrapper of `resolve_tracks(...).draft`),
  `first_of_language`, `explain` and `explain_subtitles` (wrappers of
  `audio_stage(...).decisions` and `subtitle_stage(...).decisions`) had no production caller
  except `JobService.explain` for `draft_tracks`. Plan 05 §C-12 named `explain(defaults, source)`
  as the function that "feeds the live preview"; the preview goes through `JobService.explain`.
- **BAT-01**: `resolve_group` and the `group` parameter of `BatchService.resolve` had no caller
  outside tests. The route `/batch/resolve` does not send a group
  ([0050](0050-s2-jobs-batch-presets-routes.md) item 6) and `reframe batch` uses
  `resolve_batch`, which marks near members itself. 0040 §8 and plan 04 "Core API" name
  `resolve_group`.
- **BAT-02**: `merge_template`, `SECTIONS`, `SECTION_FIELDS` and `BatchService.merge` had no
  caller outside tests. 0050 item 10 already left `batch.merge` out of the HTTP API; the frontend
  copies sections itself (`frontend/src/components/batch/clipboard.ts`). 0040 §8 and plan 04
  "Core API" name `merge_template`.
- **BAT-12**: to give one issue per problem (0040 R1-4, 0031 §6), a keyword
  `container_codecs: bool = True` went through `lint_defaults`, `resolve_tracks`, `resolve` and
  `draft_from_preset` (six signatures before Q-6.6 merged `lint_rules` and
  `resolve_with_tracks` into them). Four callers passed `False`; only the preview (`JobService.explain`)
  needed `True`, because validation does not run there.

Plan 05 line 11 says that only the `Reframe` facade and `reframe.models` are public; the rest
"can change". Choices D-6, D-7, D-9 and D-21 of
[decisions-taken.md](../simplify/decisions-taken.md) accept these changes.

## Decision

1. `JobService.draft(source, preset=None, *, output=None, validate=None)`. `validate`, when
   given, validates the drafted job in place of the service. `OwnerJobs.draft` probes first, as
   before (a `ProbeError` comes before an unknown preset name raises), then calls
   `app.jobs.draft(media, chosen, output=output, validate=self._validate)`. The draft is the
   same; `test_a_client_drafts_as_the_in_process_draft` keeps guarding it.
2. `batch/draft.py` (`draft_tracks`, `first_of_language`), `batch.explain.explain` and
   `explain_subtitles` are removed. The track draft is `resolve_tracks(template, source).draft`;
   the per-track decisions are `audio_stage(...).decisions` and `subtitle_stage(...).decisions`.
3. `resolve_group` and `BatchService.resolve(group=)` are removed. `BatchService.resolve` gives
   its rows in episode order. A group is resolved file by file with `resolve`. Only
   `resolve_batch` marks a near member of a group (`batch.near_match`), as the route already
   did. `BatchResolution.group` stays: `resolve_batch` fills it.
4. `merge_template`, `SECTIONS`, `SECTION_FIELDS` and `BatchService.merge` are removed.
   *Apply to group* stays `derive_template` with a `base` (`POST /api/batch/derive`). The
   `TemplateSection` literal stays the list of sections.
5. The defaults lint never reports `defaults.codec_not_in_container`. The check is the public
   `reframe.batch.lint.container_codec_issues(defaults, container, definitions)`, and only
   `JobService.explain` adds it, when the template has no explicit audio rules (when the defaults
   decide the audio). The keyword `container_codecs` is removed from every signature. The rule
   of 0040 R1-4 and 0031 §6 stays: one issue per problem. Validation reports
   `container.codec_unsupported` on the job path; the preview reports
   `defaults.codec_not_in_container`.

## Consequences

- The public core API loses `reframe.batch.draft_tracks`, `first_of_language`, `explain`,
  `explain_subtitles`, `resolve_group`, `merge_template`, `SECTIONS`,
  `reframe.batch.derive.SECTION_FIELDS`, the facade member `batch.merge` and the parameter
  `BatchService.resolve(group=)`. No HTTP route changes; the OpenAPI schema is the same.
- The "Not exposed" table of [06-web-app.md](../plan/06-web-app.md) loses its `batch.merge`
  row (the member is gone).
- In the preview, the codec issue now comes after the other lint issues
  (`defaults.bitrate_snapped`, `defaults.rule_unused`), not between them. The issue itself is
  the same.
- `docs/core-breakdown.md` and `docs/m2-breakdown.md` still name the removed functions. They
  are records of earlier waves and are not changed.

## Plan changes

- [04-batch-mode.md](../plan/04-batch-mode.md) "Core API": `merge_template` and `resolve_group`
  removed; a note on how a group is resolved and how *Apply to group* works.
- [05-core.md](../plan/05-core.md) §C-12 "Audio and subtitle defaults": the decisions come from
  `audio_stage` / `subtitle_stage`; `JobService.explain` feeds the preview.
- [06-web-app.md](../plan/06-web-app.md) "Not exposed": the `batch.merge` row removed.
- [docs/status.md](../status.md) C-12, S-2 and the audio-tracks feature row name the new
  functions; Q-6.15 is done.
- Status lines of 0040 and 0031: "amended in part by 0090".
