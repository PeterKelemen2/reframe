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
