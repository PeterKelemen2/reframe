# 0050 — S-2 routes of definitions, languages, jobs, naming, batch and presets

- Status: accepted
- Date: 2026-10-22
- Steps: S-2 (task 1e of [m3-breakdown.md](../m3-breakdown.md))

## Context

The S-2 table of [06](../plan/06-web-app.md#s-2-rest-api) gives each route a body and a short
purpose. Building the routes of definitions, languages, jobs, naming, batch and presets on the
facade showed what the table leaves open:

- `jobs.plan` returns an `EncodePlan` **or** the issues; the table does not say which status the
  issues get ([0045](0045-m3-server-order-and-contract.md) leaves it to this task).
- `jobs/geometry` and `jobs/hdr-metadata` take `{job}`, but the facade has no geometry method,
  and `jobs.hdr_metadata(job, source)` needs the probed source.
- `presets/defaults/preview` has `{audio_defaults, subtitle_defaults, source_ids}`; the codec
  rules depend on the container (WebM cannot hold AAC: `defaults.codec_not_in_container`), which
  the body does not carry.
- `naming/preview` has `{naming, source_ids, job?}`. With a job, `jobs.name_job(job, source,
  naming=…)` names it. Without one, the only facade method is `jobs.name(path, preset=…,
  template=…)`, which takes naming options and a container only as a preset's.
- `batch/resolve` and `batch/resolve-run` take overrides; the core keys them by file path, the API
  by `source_id`. `Apply to group` merges a job's sections into the group's template, not into
  the job's preset, but the table's `batch/derive` body has no template.
- Preset routes: the table lists the paths, not the answers. The facade's change methods return
  a `ValidationIssue` on a refusal (built-in, name clash, unknown id, read-only store, failed
  write); `export` and `import_` return dataclasses, not models.
- There is no language-list model in the core (`reframe.languages.LanguageEntry` is a
  dataclass).
- Every client path must pass the jail (0045 item 13). A template's only path is
  `naming.output_folder`; a preset import file is raw JSON.

## Decision

1. **Plan with errors.** `POST /api/jobs/plan` answers `422` `jobs.invalid` (problem+json) with
   the issues in `issues`; `200` is always an `EncodePlan`. `validate` and `dry-run` answer `200`
   with the issue list (0045).
2. **Geometry.** `POST /api/jobs/geometry {job}` answers `{source: SourceGeometry | null,
   geometry: Geometry | null}`: `source` is `null` for a source without video, `geometry` is
   `null` for a copied video (and without video). The source comes from
   `Reframe.sources.probe(job.source.path)` (the probe cache; after the jail); a probe failure is
   `probe_problem`. The router calls `reframe.dimensions.source_geometry` and `compute_geometry`
   with the command builder's rule (a job that deinterlaces crops on the frame grid). So this
   handler makes two calls (probe, then the pure functions), and repeats a rule that the builder,
   the preview graph and validation also have: a core function `job_geometry(job, source)` would
   remove the copy (for the lead). `hdr-metadata` gets its source the same way (probe, then
   `jobs.hdr_metadata`).
3. **Explain** takes `template: JobTemplate | str | null` (a template, a preset id or name, or
   the default preset) and `container?`, as `jobs.explain` does.
4. **Defaults preview** adds `container?` to the body. The template is a new one with only the
   given defaults (no explicit track rules), explained per source with `jobs.explain(…,
   container=…)`. The answer is one `TrackDraft` per source, in the order of `source_ids`.
5. **Naming preview** adds `container` (default `mkv`) and makes `naming` optional. With `job`,
   each source is named as that job would be (`jobs.name_job`; `naming` `null`: the job's preset's
   options, else the settings'). Without it, from the path alone (`jobs.name`; the media variables
   are empty), with a preset made in the router from `naming` and `container`: that is the one
   way `jobs.name` takes them. The answer is one `NameResult` per source, in order.
6. **Batch.** Overrides are keyed by `source_id`; the router maps each id to the registry's path
   (an unknown id is `404 source.unknown`). `batch/derive` adds `base?` (the group's template; `null`:
   the job's preset, else the default), passed to `batch.derive`. `resolve`'s `group` parameter is
   not exposed: its member paths would be more client paths, and `resolve-run` resolves groups.
   `resolve-run` answers `{grouping, resolutions}`. Group members are named by path, as
   `GET /api/sources` names the sources.
7. **Presets.**
   - `GET /api/presets` → `{presets, default_id}` (two reads of the preset service, no I/O).
   - `POST /api/presets` and `POST /api/batch/save-preset` → `201` with `Location:
     /api/presets/{id}`.
   - `PUT /api/presets/{id}` takes a whole `Preset`; its `id` must be the path's (else `422
     presets.id_mismatch`). It is `presets.save`: create or replace; a rename is a `PUT` with a
     new name.
   - `DELETE` answers `200` with the deleted preset. `POST …/{id}/default` answers with the default
     now in effect; the built-in default is made the default again by its own id.
   - A refused change is `issue_problem` with the issue: `404` `preset.not_found`; `409`
     `preset.built_in`, `preset.name_conflict`, `preset.newer_version`, `presets.read_only`; `503`
     `presets.write_failed`; `422` for every other code (`preset.name_empty`, `preset.invalid`).
   - `POST /api/presets/import?on_conflict=rename|replace|skip` reads the raw body, at most 4 MiB
     (`413 presets.import_too_large`, counted while it is read), then `json.loads`; a body that is
     not a JSON object is `422 presets.import_invalid`. The core reads the document as it reads the
     file (migrations, newer presets). The answer is always `200` with the report (`imported`,
     `renamed` as `{name, new_name}`, `replaced`, `skipped`, `issues`); a refused import has its
     reasons in `issues`.
   - `GET /api/presets/export?ids=…` (repeated; none: every user preset) → `{document, issues}`:
     the export file and the warnings for presets of a newer Reframe in it.
   - `POST /api/presets/diff` with an unknown preset is `404 preset.not_found`.
8. **Definitions and languages.** `GET /api/definitions` → `{definitions, naming_variables}`.
   `GET /api/languages` → `{languages: Language[]}`, where `Language` is a server model with the
   fields of the core's `LanguageEntry`, ordered by English name. Both answers are rendered once
   (in a worker thread) and carry an `ETag` (a hash of the bytes) and `Cache-Control: no-cache`;
   an `If-None-Match` that names the ETag (also weak, `W/…`, or `*`) gets `304` with no body.
   `GET /api/definitions/encoders/{id}/options` with an unknown video encoder is `404
   definitions.unknown_encoder` (the facade gives an empty list).
9. **Jail.** Every job goes through `security.jail_job`, and every template's or naming options'
   `naming.output_folder` through `security.jail_write`, before the facade sees them: in
   `jobs/{validate,plan,geometry,dry-run,hdr-metadata,explain}`, `naming/preview`, every batch
   route but `group`, and `presets` create, save, diff and import. For an import the router reads
   `presets[*].naming.output_folder` from the raw JSON (every preset schema so far keeps the folder
   there); an entry of another shape is left to the store, which refuses it.
10. **Facade methods not exposed** (for 2a's list in 06): `batch.merge` (copies whole sections of
    one template into another; `batch/derive` with `base` covers *Apply to group*, and a client
    copies sections itself), `presets.rename` (a `PUT` with the new name), `presets.duplicate`
    (`GET` then `POST /api/presets`; a clash is a `409` whose fix names a free name),
    `presets.find` (the routes take ids; `jobs/draft`, `explain` and the batch routes accept a name
    or an id through the facade's own lookup), `jobs.media_files` (folders are listed and probed
    by the `fs` and `sources` routes). `jobs.preview_clip` and `jobs.preview_clip_path` belong to
    the preview routes.

## Consequences

- The generated client gets a typed `EncodePlan` for `jobs_plan` and reads the issues from the
  problem body.
- A web-mode draft names its output beside the source while the naming options say
  `same_as_source` (the default); the write jail then refuses that job in `validate`, `plan`
  and the queue. Web mode needs an output folder below an output root by default (for the lead:
  settings or S-1).
- `presets.write_failed`'s message names the server's config folder (it comes from the core).
- The defaults preview shows the defaults alone: a group with explicit track rules is previewed
  with `batch/resolve`.

## Plan changes

- [06](../plan/06-web-app.md) §S-2: the rows of `jobs/plan`, `jobs/geometry`, `batch/derive`,
  `batch/resolve-run`, the presets, `presets/defaults/preview`, `naming/preview`, `definitions`
  and `languages` give the answers and the added fields above.

## Follow-up 2026-10-22: web-mode output folder and override jail

### Context

1. With the default naming (`output_folder_mode: same_as_source`), a web-mode draft saves its
   output beside the source, in a media root. The real write jail (S-1,
   [0046](0046-s1-login-sessions-jail-and-request-checks.md)) refuses that job with a 403 in `validate`, `plan` and the queue:
   the client sees a refusal, not what to do. The owner decided: **web mode refuses "same as
   source"**; the user sets a fixed output folder inside an output root (Settings → Output), and
   validation says so with a fix.
2. Task 2a's jail sweep found that `batch/resolve` and `batch/resolve-run` passed the per-file
   overrides to the facade unjailed. An override `add /job/subtitles/-` with an external subtitle
   outside the roots was resolved and validated, and `subtitle.external_missing` told whether that
   file exists; a `/job/source/path` override made a job that reads outside the roots.

### Decision

1. **`output.folder_required`** (error, path `output.path`): in web mode, an output path that the
   write jail refuses as outside the roots is this issue instead of a 403. Its fixes: target
   `settings`, `add /output/naming/output_folder_mode "fixed"` and `add
   /output/naming/output_folder <first output root>` (no settings fix when the server has no
   output root); and, when there is exactly one output root, target `job`, `replace /output/path
   <root>/<file name>`. Any other refusal of the jail (a relative path: `400 path.invalid`) is
   still raised. Desktop mode never has the issue (its jail allows every path).
2. Where it shows:
   - `jobs/validate`: `200` with the issue. The facade validates the job **without** its output
     path (an outside file is never looked at: an existing one would otherwise give an overwrite
     or rename issue, which tells that it exists); the `output.no_path` this gives is replaced by
     the folder issue.
   - `jobs/plan`, `jobs/dry-run`: `422 jobs.invalid` with the issue; the facade is not called.
   - `jobs/draft`, `jobs/draft-remux`: the issue is added to the draft's issues.
   - `batch/resolve`, `batch/resolve-run`: added to each row concerned, whose `status` becomes
     `error`.
   - `naming/preview`: added to each `NameResult` whose `path` is outside, **with the settings fix
     only**: the preview is where the naming options are edited, and a `job` fix has no job there.
   - `jobs/geometry`, `jobs/hdr-metadata`, `batch/derive` and `naming/preview` with a job take
     such a job (they write nothing and do not use its output path).
   Every other path of the job still passes `security.jail_job` (a source outside the media roots
   stays `403`). The queue route keeps the jail's 403: nothing outside is queued.
3. **Overrides.** Before the facade sees them, the router applies each override as the batch
   service will: `reframe.batch.resolve.resolve` (pure) with the template the service picks (the
   given template, else the preset of that name or id, else the default; the same lookup as
   `BatchService._template`), the settings' languages and the definitions; then
   `security.jail_job` on the job it makes. This is airtight because it is the same function on
   the same input: a JSON patch can put a path in any field of the job (an external subtitle, the
   source, the output, a field added later), and `jail_job` walks every `Path` of the model. A walk
   over the patch values instead would have to know which strings become paths, and a `test` op
   can make a patch apply under one template and fail under another. The cost: each override is
   resolved twice (once here, once in the service; pure, in a worker thread). An override of an id
   that is not among `source_ids` is jailed too (by its own source).

### Consequences

- A web client sees `output.folder_required` with a button instead of a 403 until the owner sets
  the output folder. `GET /api/system` could report the missing folder at start-up (task 1d's
  route; for the lead).
- `preview/render` and `preview/clip` (task 1d) still jail the whole job: a draft whose
  output is outside the roots gets a 403 there, although the preview writes only into the cache.
- `presets.find` is now reached (the override jail looks a template up as the service does): it
  left 06's "Not exposed" table.

### Plan changes

- [06](../plan/06-web-app.md) §S-2: the rows of `jobs/draft`, `validate`, `dry-run`,
  `draft-remux`, `batch/resolve`, `resolve-run` and `naming/preview`; `presets.find` left the
  "Not exposed" table.
