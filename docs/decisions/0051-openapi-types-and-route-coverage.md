# 0051 — OpenAPI types, the API contract check, facade coverage and the jail sweep

- Status: accepted
- Date: 2026-10-22
- Steps: S-5, Q-2.3, S-2 (task 2a of [m3-breakdown.md](../m3-breakdown.md))

## Context

06 §S-5 says to export `openapi.json` from `create_app()` without a server and run
`openapi-typescript`; 09 §Q-2.3 says CI regenerates the file and fails on a diff. It leaves
open how the WebSocket messages get TypeScript types (0047: "S-5 can add the four models to the
document's components"), where `openapi-typescript` comes from, and how the generated file
lives with the frontend's lint and format tools. The S-2 "Done when" needs a check that every
public facade member is reached by a route or listed as not exposed, and that every route is
tested.

What the tools do (checked on 2026-10-22, FastAPI 0.159.1, openapi-typescript 7.13.0, npm
12.2.1, oxfmt 0.72.0, oxlint 1.x, actionlint 1.7.12):

1. **openapi-typescript 7.13.0 (the latest; `next` is an older rc) declares the peer
   `typescript@^5.x`.** `npm install --save-dev --save-exact openapi-typescript@7.13.0` in
   `frontend/` (TypeScript 6.0.3) fails: `ERESOLVE unable to resolve dependency tree … peer
   typescript@"^5.x" from openapi-typescript@7.13.0`. With the npm override
   `"overrides": {"openapi-typescript": {"typescript": "$typescript"}}` it installs, uses the
   project's TypeScript 6.0.3 (`npm ls typescript`: `deduped`) and generates the file.
2. **The output is deterministic**: two runs of `scripts/gen-api.sh` give the same bytes
   (SHA-256 the same; `scripts/gen-api.sh --check` passes right after a run). The document is
   the same in processes with different `PYTHONHASHSEED`s
   (`tests/test_openapi.py::test_the_export_is_the_served_document_whatever_the_process_and_its_environment`).
3. **oxfmt rewrites the generated file** (`npm run fmt:check`: "Format issues found" in
   `src/api/schema.d.ts`: 4-space indents and double quotes). **oxlint accepts it**
   (`oxlint --deny-warnings src/api/schema.d.ts`: no findings). `vue-tsc` skips it
   (`skipLibCheck`).
4. **FastAPI generates the schemas of `app.webhooks` routes in the same pass as the paths**
   (`get_openapi(…, webhooks=…)` → `get_fields_from_routes(routes + webhooks)`), so a model used
   by both gets one component, named the same way.
5. **FastAPI 0.159 keeps an included router as one `app.routes` entry** (`_IncludedRouter`), so
   the routes are read from each router module's `router.routes`.

## Decision

1. **Export.** `scripts/export-openapi.py` deletes every `REFRAME_*` variable from its own
   environment (a developer's `REFRAME_HOST=0.0.0.0` would otherwise stop `ServerConfig()`),
   creates `create_app(ServerConfig())`, never runs its lifespan, and writes
   `app.openapi()` as JSON (indent 2, UTF-8). `scripts/gen-api.sh` runs it into a temporary
   folder, then `npm exec --offline openapi-typescript` from `frontend/` →
   `frontend/src/api/schema.d.ts`. `scripts/gen-api.sh --check` writes nothing and exits 1 with
   a `diff -u` when the file differs. `npm run gen:api` in `frontend/` runs the script.
2. **openapi-typescript 7.13.0, pinned exactly**, with the override of finding 1. It only
   prints TypeScript declarations through the compiler's printer, which TypeScript 6 keeps.
   Revisit when a release accepts TypeScript 6 (then drop the override).
3. **The WebSocket messages** are a webhook of the app (`reframe_server.openapi.install`, called
   by `create_app`): its body is `AuthMessage`, its answer `ServerMessage`, a root model of
   `Hello | EventMessage | Heartbeat` with `type` as the discriminator. FastAPI puts them and
   every core event model into `components.schemas` (finding 4); `install` then removes the
   `webhooks` key, because a webhook means an HTTP request from the server, and a generated
   client must not get an operation for `/api/events`. The frontend reads
   `components["schemas"]["ServerMessage"]` and `["AuthMessage"]`.
4. **The generated file is committed and left out of oxfmt** (`ignorePatterns` in
   `frontend/.oxfmtrc.json`; finding 3). oxlint still checks it.
5. **Q-2.3** is a job of its own in `ci.yml`, `api-contract` (Ubuntu): uv, Node, `uv sync
   --frozen`, `npm ci`, `scripts/gen-api.sh --check`. Neither existing job has both Python and
   Node. Not on Windows: the script and the document do not depend on the platform.
   `actionlint` 1.7.12 (with shellcheck 0.11) finds nothing in the workflow.
6. **Facade coverage** (`tests/test_facade_coverage.py`). The public members are read from the
   running facade: `Reframe`'s own (its services excluded) and those of each service
   (`tools` … `events`), instance attributes included. Which members a route reaches is read
   from the source: the handler of each route of the OpenAPI document (and `WS /api/events`),
   and the server functions and classes it calls, follow the attributes of variables whose
   class is `Reframe`, a service class, or a server class (from annotations, assignments and
   `self.x = param` in `__init__`). A member reached by no route must be in the "Not exposed"
   table of 06 §S-2, with its reason; a member in the table that a route reaches, or that no
   longer exists, fails too. So `tasks.start`, `tasks.value` and `tasks.wait` (0048 item 9)
   are not in the table: the probe, rescan and frames routes use them on their own tasks.
7. **Every route is called by a test.** The same file reads every route test file (the sweeps
   excluded) for client calls (`.get(…)`, `.post(…)`, `.request(method, …)`), resolves the URL
   from string constants, f-strings, `.format()`, local and module constants and the
   `parametrize` cases (an unknown part is a sample segment), and matches it with the method
   against each path of the document. A route that no test file calls fails. Running the server
   suite again under coverage would show the same, but costs about two minutes per run.
8. **operationIds** (`tests/test_openapi.py`): unique in the document, and each one is
   `<tag>_<route name>` of the router route with that path and method.
9. **Jail sweep** (`tests/test_jail_sweep.py`): a table of every place in a request where a
   client names a path (one row per input: a route with a job and a naming folder has two). A
   test reads the OpenAPI document and fails when the set of operations with a path in their
   request (a `format: path` string, a field or parameter named `path`, `paths`, `*_path`,
   `*_folder`, `*_file` or `*_dir`, or a value of any shape: a JSON patch value, a raw
   document) is not the table's. Each row sends three paths to a web server with the real jail:
   one in the outside folder, a `../` escape from its root and a link below its root to the
   outside folder; each must be a 403 `path.outside_roots`. The first route of each router
   module is sent with `Host: evil.example` (400 `request.host`); `WS /api/events` is upgraded
   with it (403).

## Consequences

- A change to a route's docstring, model or path changes `schema.d.ts`; CI fails until it is
  regenerated and committed.
- A new public facade member, or a route removed, fails the coverage test until a route
  reaches the member or 06 lists it. The source reading can miss a call made through
  `getattr` or a variable whose class it cannot tell; such a member then needs a table row.
- **Route bug found** (for the task that wrote the routes, 1e): `POST /api/batch/resolve` and
  `/resolve-run` do not jail the per-file `overrides`. An override that adds an external
  subtitle outside the media roots is resolved and validated, and the answer says whether that
  file exists (`subtitle.external_missing`). The sweep's two rows are `xfail(strict=True)`
  until the routes jail the patched jobs (or every path in the override values).

## Plan changes

- [06](../plan/06-web-app.md) §S-5: the export script, the WebSocket models, the check;
  §S-2: the "Not exposed" table.

## Follow-up (review), 2026-10-22

The test-quality findings of [0052](0052-m3-server-review.md) for the files of this task.
0052 makes the sweep the proof that each route passes each of its path inputs to the jail; the
route tasks delete their tests that replaced the jail with a fake where the sweep sends the
same input to the same route.

**The sweep** (`tests/test_jail_sweep.py`), item 9 above, changes:

1. **One hostile path per input**: a symbolic link below the input's root (`<root>/escape`)
   to the outside folder, which holds `film.mkv`. The `outside` and `../` paths are gone:
   `test_security_jail.py` proves that the jail refuses each kind of escape; the sweep proves
   that each route uses the jail. Of the three, a link is the escape that a check of its own
   in a route (the path normalised, then compared with the roots) would also let through.
2. **A refused request changes nothing.** Each row compares, before and after the request:
   the tool runs whose arguments name a path through the link (the capability checks of the
   server's start run at the same time, so other runs are not the request's), the task list,
   the queue, the presets, the settings, and the files below the output root, the outside
   folder and the config folder. The `queue_add` row sends a job the jail allows before the
   refused one, so a route that queued jobs one by one fails it.
3. **The per-router foreign-`Host` rows are deleted**: one middleware refuses the host; S-1's
   tests cover HTTP and the WebSocket.
4. **The link skip of `test_security_jail.py`**: a platform or user that cannot make links
   (Windows without the privilege) skips the row instead of passing or failing for the wrong
   reason.
5. **R-2 waits as `xfail(strict=True)`** (reason "R-2, task 1d"): a link to a file outside the
   roots, inside a media folder that `POST /api/sources` expands, must not reach ffprobe or
   become a source. The test does not assume how the route refuses it (a 403, or a skip in
   the task). Checked with a fix of the route: it then passes, and the strict mark fails the
   run until the mark is removed. R-7 (the template resolved twice by the batch routes) needs
   a preset change between the two resolutions, a race the sweep cannot set up.

The fake-jail route tests whose assertions the sweep now makes, by route:

| Route test (file) | Sweep row(s) | Assertions taken over |
|---|---|---|
| `test_list_passes_the_path_to_the_jail` (`test_fs.py`) | `fs_list.path` | 403 `path.outside_roots` |
| `test_probe_passes_each_path_to_the_jail` (`test_sources.py`) | `sources_probe.paths` | 403, no task started |
| `test_a_job_route_passes_the_job_to_the_jail` (`test_preview.py`) | `preview_render.job`, `preview_clip.job` | 403, no frames or clip task |
| `test_the_job_passes_the_jail_before_any_file_is_read` (`test_jobs.py`) | `jobs_validate`, `jobs_plan`, `jobs_geometry`, `jobs_dry_run`, `jobs_hdr_metadata` (`.job`) | 403, no tool run on the source |
| `test_explain_jails_the_templates_naming_folder` (`test_jobs.py`) | `jobs_explain.template` | 403 |
| `test_the_naming_folder_and_the_job_pass_the_jail` (`test_naming.py`) | `naming_preview.naming`, `naming_preview.job` | 403 |
| `test_derive_jails_the_job` (`test_batch.py`) | `batch_derive.job` | 403 |
| `test_a_templates_naming_folder_passes_the_jail` (`test_batch.py`) | `batch_derive.base`, `batch_resolve.template`, `batch_resolve_run.template`, `batch_save_preset.template` | 403, no preset saved |
| `test_import_jails_each_naming_folder` (`test_presets.py`) | `presets_import.file` | 403, no preset saved |
| `test_a_templates_naming_folder_passes_the_jail` (`test_presets.py`) | `presets_create`, `presets_save`, `presets_diff` | 403, the stored preset unchanged |
| `test_every_job_goes_through_the_jail` (`test_queue.py`) | `queue_add.jobs` | 403, neither job added |
| `test_a_new_folder_goes_through_the_write_jail` (`test_settings.py`) | `settings_update.patch` | 403, the settings unchanged |

Not taken over, because no client names a path in these requests or they test an allowed
path: `test_duplicate_goes_through_the_jail` (`test_queue.py`: the stored job is jailed
again), `test_a_folder_below_an_output_root_can_be_listed` (`test_fs.py`) and
`test_a_folder_the_patch_does_not_change_is_not_checked_again` (`test_settings.py`). The
fake-jail assertions that the jail got exactly the client's path are not repeated either: a
route that jailed another path would let the link through.

**The other files:**

- `tests/test_openapi.py`: one OpenAPI document per file (a module fixture made from
  `create_app` without a lifespan), and the export test runs one subprocess instead of two.
  It runs the script with a hash seed that differs from the test process's and with
  `REFRAME_HOST=0.0.0.0`, and compares its output with the in-process document as JSON text,
  so that the order of the keys counts.
- `tests/test_facade_coverage.py`: the facade's members, the document and which routes reach
  which member are read once per file (a module fixture that starts one server), not once per
  test. The tests themselves are unchanged.
- Rows and tests deleted because another test follows the same path: the 18 foreign-`Host`
  rows (item 3) and the `outside` and `../` cases of each of the 25 sweep rows (item 1). The
  other tests each catch a defect of their own (mutation-checked).
