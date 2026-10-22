# 0046 — S-1 security: password hash, sessions, rate limit, request checks and the jail

- Status: accepted
- Date: 2026-10-22
- Steps: S-1

## Context

The plan ([06](../plan/06-web-app.md) §S-1, [0042](0042-one-scheduler-process-and-cli-clients.md)
item 2, [0043](0043-plan-review-before-m3.md) item 3, the contract of
[0045](0045-m3-server-order-and-contract.md)) sets the auth modes, the local token, the path
jail, the `Host` check, CORS and the security headers. It leaves open the hash function, how
sessions are kept, the login rate limit, which `Origin` counts as the server's own, what the
default `allowed_hosts` are on a wildcard bind, what the jail does with relative paths,
in-place edits and path fields added later, what the docs page needs, and how a frontend learns
the auth mode.

What was checked (2026-10-22, Python 3.14.8 with OpenSSL 3.6.5, FastAPI 0.159.1, Starlette
1.9.0, uvicorn 0.54.0, websockets 17.3, Firefox 158 headless; scripts in the agent's
scratchpad, the results are asserted by the tests named here):

1. **scrypt cost.** `hashlib.scrypt(n=2**17, r=8, p=1)` takes 0.34 s on an 8-core desktop
   (`n=2**16`: 0.17 s, `2**15`: 0.09 s). Without `maxmem` OpenSSL refuses it:
   `ValueError: [digital envelope routines] memory limit exceeded` (its default limit is
   32 MiB). `test_set_password_from_a_pipe` runs the real cost from `--set-password` to a login.
2. **`Path.resolve(strict=False)`** ignores `OSError`, but `os.lstat` raises `ValueError` for a
   NUL (`lstat: embedded null character in path`) and `UnicodeEncodeError` (a `ValueError`) for
   a lone surrogate outside `\udc80`–`\udcff`. Both would be a 500 if not caught.
3. **WebSocket refusal.** An ASGI app that sends `websocket.close` before `accept` makes
   uvicorn answer the upgrade with HTTP 403 (the `websockets` client raises `InvalidStatus`,
   status 403). `websockets.asyncio.client.connect("ws://evil.example:PORT/…",
   host="127.0.0.1", port=PORT)` sends a foreign `Host` to a local server. The `websockets`
   client sends no `Origin` unless asked.
4. **The docs page.** FastAPI's Swagger UI page loads `swagger-ui-bundle.js` and
   `swagger-ui.css` from `https://cdn.jsdelivr.net`, its icon from
   `https://fastapi.tiangolo.com`, and starts with an inline `<script>`. With the docs CSP of
   item 9, headless Firefox (driven over WebDriver BiDi) renders every operation, expands them
   and runs "Try it out" (answers 200, 409, 401) with no console error. Without
   `'unsafe-inline'` in `script-src` the page stays empty and Firefox logs "blocked an inline
   script (script-src-elem)". `style-src` needs no `'unsafe-inline'`. The inline script's hash
   depends on the request's `root_path`, so a hash source would break behind a proxy prefix.
5. **`hmac.compare_digest`** raises `TypeError` for two `str` with a non-ASCII character. A
   header with UTF-8 bytes reaches Starlette as Latin-1 text, so a token like `tést` would be a
   500; both sides are compared as UTF-8 bytes.
6. **File mode.** `tempfile.mkstemp` creates its file with mode 0600, and `os.replace` keeps
   it: `auth.json` written through `reframe.settings.JsonDocumentFile` is 0600
   (`test_changing_the_password`).

## Decision

1. **Hash: stdlib scrypt**, no new dependency. `n=2**17, r=8, p=1` (OWASP's minimum: 128 MiB),
   a 16-byte salt, a 32-byte key, `maxmem` 256 MiB. `auth.json`:
   `{"schema_version": 1, "password": {"algorithm": "scrypt", "n", "r", "p", "salt", "hash"}}`
   (base64). The cost is stored with the hash, so a later cost keeps old hashes working. A
   write keeps the file's other top-level fields. The password is NFC-normalised and encoded as
   UTF-8 (`surrogatepass`) first, so the same password typed on two systems matches. A new
   password needs 8 characters (HTTP and `--set-password`); the request fields take at most
   1024. Why not argon2: `argon2-cffi` is a compiled dependency (also in the frozen desktop
   build) for one single-user login; scrypt is memory-hard as well and ships with Python.
2. **`auth.json`** is written atomically by `JsonDocumentFile` (mode 0600 on POSIX). It is
   read again at each login, so `--set-password` takes effect in a running server. A missing,
   damaged or unusable file makes login a 503 `auth.no_password` (never a 500), and the server
   warns at start. **Windows**: no extra code; the file gets its folder's ACL, and the default
   config folder (`%APPDATA%\Reframe`) is readable only by the user and administrators.
3. **Sessions** are random 256-bit tokens kept in memory (only their SHA-256), valid 30 days
   from login, at most 1000 (the oldest ends first). A restart ends them all. Logout ends the
   session on the server. `PUT /api/auth/password` ends every session and gives the caller a
   new one when it came with the cookie. A running server keeps its sessions after
   `--set-password` until it restarts (the command says so); checking `auth.json` on every
   request would cost file I/O per request. Cookie `reframe_session`: `HttpOnly`,
   `SameSite=Strict`, `Path=/api`, `Max-Age` 30 days, `Secure` when the request came over
   HTTPS (behind a TLS proxy on the same machine, uvicorn's proxy headers make it so).
4. **Rate limit**: 5 wrong passwords per client within a sliding 60 s, then 429
   `auth.rate_limited` with `Retry-After`. A client is an IPv4 address or an IPv6 /64 (a
   client can use any address of its /64; an IPv4-mapped address counts as IPv4). Password
   checks run one at a time in a worker thread, so parallel guesses cannot pass the limit
   together. At most 4096 clients are remembered (the least recent is forgotten first). A
   right password clears the client's failures; a wrong `current` in `PUT /api/auth/password`
   counts as a failure. No global limit: one attacker could then lock the owner out (the local
   token would still work).
5. **Auth routes** (tag `auth`; the router has no `require_auth`):
   `GET /api/auth/status` → `{mode, authenticated}` (**new**: a frontend needs the mode to
   choose between a login form and the token); `POST /api/auth/login` `{password}` (409
   `auth.not_password_mode` outside password mode, 401 `auth.invalid`, 429, 503);
   `POST /api/auth/logout`; `PUT /api/auth/password` `{current, new}` (needs `require_auth` and
   the current password: 403 `auth.wrong_password`, 422 `auth.weak_password`, 500
   `auth.not_saved`). Each answers `AuthStatus`. A 401 of `require_auth` is `auth.required`
   (no credentials) or `auth.invalid` (a wrong token, an unknown or expired session, a bad
   signature), with `WWW-Authenticate: Bearer realm="reframe"`.
6. **`Host` check** (every mode, HTTP and WebSocket upgrade, a middleware). The loopback names
   always pass, with any port. `allowed_hosts` set: those names (case and port ignored)
   **replace** the defaults. Unset: on a loopback bind nothing more; on another address that
   address and the machine's host name (`socket.gethostname()`, its first label and
   `<label>.local`); on a wildcard bind (`0.0.0.0`, `::`) also every IP address, because a DNS
   rebinding attack always sends the attacker's host name, and a Docker container binds
   `0.0.0.0` while users open the NAS address. Refused: 400 `request.host`; a WebSocket is
   closed before `accept` (uvicorn answers 403).
7. **`Origin` check**, also for HTTP (beyond the plan): a WebSocket upgrade, and a `POST`,
   `PUT`, `PATCH` or `DELETE`, whose `Origin` is not the server's own (its host and port equal
   the `Host` header), a Tauri origin, a `cors_origins` entry or a page of an `allowed_hosts`
   name is refused (403 `request.origin`). A request without `Origin` passes: it does not come
   from a browser (the CLI, curl). Why HTTP too: with `auth none` there is no credential at
   all, and `SameSite=Strict` does not separate two ports of one host, so a page elsewhere
   could send a form `POST`. Why `allowed_hosts` names: a reverse proxy that sends its own
   `Host` would otherwise make every `POST` of the public page fail.
8. **CORS**: the allowed origins are the Tauri origins in desktop mode plus `cors_origins` in
   both modes (none by default in web mode: CORS is off). All methods, the headers
   `Authorization` and `Content-Type`, `Location` and `Retry-After` exposed, no credentials
   (the desktop shell sends the token).
9. **Security headers** on every HTTP answer, refusals included: `Content-Security-Policy`,
   `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`
   (a signed URL carries its signature in the query). The app CSP: `default-src 'self';
   script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:;
   media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none';
   form-action 'self'; frame-ancestors 'none'`. Inline styles stay allowed because a Vue
   production build may insert static template parts, with their `style` attributes, as HTML
   text; S-4 checks the CSP with the real build. The docs page (`/api/docs` and its OAuth2
   redirect page): `default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net;
   style-src https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com;
   connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`
   (finding 4). The docs page and `/api/openapi.json` need no credentials: they hold no secret.
10. **Signed media URLs**: `?exp=<Unix seconds>&sig=<base64url HMAC-SHA256>` over
    `"<path>\n<exp>"` with the key HMAC-SHA256(the run's token, `"reframe media url"`), so a
    restart ends every URL. The default lifetime is 300 s; the signed path is the path the
    route sees, without a query. `require_media_access` takes the token or the cookie first; a
    URL with `exp` or `sig` that does not verify is 401 `auth.invalid`.
11. **Path jail**: only an absolute path (a relative one would resolve against the server's
    working folder): else 400 `path.invalid`, in every mode; a NUL or a character the file
    system cannot encode: 400 `path.invalid`, in every mode (finding 2). Web mode: the resolved
    path must be inside a resolved root (a root reached through a link works), else 403
    `path.outside_roots`. The detail names the path the client sent, never the resolved one,
    which would tell where a link points. The resolved path is returned. **`jail_job`** walks
    every `Path` value of the job (models, lists, dicts), so a field added later is checked: a
    path under `output` is written, every other path is read; **an in-place edit
    (`output.edit_in_place`) also writes its source** (the plan said inputs are read only), so
    its source must be below a media root and an output root. Not covered: a link swapped
    between the check and the use; the API never creates links.
12. **`--set-password`**: a terminal is asked twice with `getpass` (no echo); from a pipe the
    first line is the password (scripts, `docker exec -i`). Exit codes: 0, 1 (the two differ,
    too short, not saved), 130 (Ctrl+C).

## Consequences

- After a restart everyone logs in again. Fine for a single-user server; persistent sessions
  can come later (a key in `auth.json`) if users ask.
- Behind a reverse proxy: put the public name in `allowed_hosts` (it then replaces the
  defaults). A proxy that passes `Host` and one that sends its own both work.
- `auth.json` is a file of its own: `AppSettings` has no field for it, and the settings service
  reads and writes only `settings.json`, so `GET /api/settings` cannot show the hash and a
  settings patch cannot change the login. The route-level checks
  (`test_get_settings_holds_no_secret`, `test_put_settings_cannot_change_the_password` in
  `tests/test_auth.py`) skip until `GET/PUT /api/settings` exist.
- **Open risk outside S-1**: free text that reaches FFmpeg can name files. `filters.custom`,
  and every filter's `custom` preset text (inserted into its chain as it is, so a `,` starts a
  new filter), can add `movie=`, `drawtext=textfile=`, `frei0r=` and the like. The jail does not
  parse filter graphs, so in web mode a logged-in client could read a file outside the roots
  into its output, or load a plugin. `custom_params` file keys are already refused by
  validation. This needs its own decision (for example: no free filter text in web mode, or an
  allow-list of filters).

## Plan changes

- [06](../plan/06-web-app.md) §S-1: the auth routes (with `GET /api/auth/status`), the hash
  and `auth.json`, sessions and the rate limit, the `Origin` check for HTTP, the
  `allowed_hosts` defaults and the wildcard bind, CORS with `cors_origins`, the headers on every
  answer and the docs page, the jail's rules (absolute paths, `edit_in_place`).

## Follow-up (2026-10-22): free filter text in web mode

The owner decided on the open risk above: **web mode accepts free filter text only through an
allow-list of filters**. Desktop mode does not change.

### Where free text reaches a filtergraph

Read in `reframe.command` (`filtergraph.py`, `video.py`, `audio.py`, `subtitles.py`,
`builder.py`) and `reframe.definitions`:

- `FilterConfig.custom`, put into a chain as it is wherever the chain has `{custom}`: the
  Custom filter's whole chain (`{custom}`), and the `custom` presets of detelecine
  (`fieldmatch={custom},decimate`), interlace detection (`idet=`), deinterlace (`bwdif=`,
  `yadif=`), denoise (`nlmeans=`, `hqdn3d=`), deblock (`deblock=`), colorspace (`zscale=`,
  `libplacebo=`), sharpen (`unsharp=`, `cas=`) and chroma smooth (`unsharp=`).
- Nothing else. The external subtitle path and `charset` of a burn-in are quoted with
  `quote_value` (the core runs real FFmpeg on file names with every special character);
  `preset`, `tune` and `implementation` must name an entry of the definitions (otherwise the
  planner refuses the job); the audio chain is built from numbers and `Literal` values
  (`aresample`, `volume`, `loudnorm`); `dimensions.scaler` is a `Literal`;
  `custom_params` is an encoder argument, not a filter (validation refuses its file keys).
  Outside the job: the setting `encoders.vaapi_device` reaches `-init_hw_device` as text (a
  device path); it is a settings matter (S-2 settings route), not a filtergraph.

### Decision

1. `security.jail_job`, web mode only, refuses a job whose free filter text is not safe: 403
   `filter.not_allowed`, with a detail that names the job's filter and the reason (the FFmpeg
   filter that is not allowed, a `;`, a label, a quote left open, …). Every route that takes
   a job already calls the jail.
2. **The parser** (`reframe_server.filtertext.parse_graph`) is a port of FFmpeg's
   `avfilter_graph_segment_parse` and `av_get_token`: chains split at `;`, filters at `,`,
   `[label]`s before and after a filter, `name@instance=options`, `'…'` quoting and `\`
   escapes outside quotes, spaces trimmed. It was checked against the real ffmpeg with
   `-print_graphs_file` (the table under "Filtergraph syntax and free filter text" in
   `testdata/README.md`, and a test). It refuses what FFmpeg reads in a way the check cannot
   follow: a quote that is not closed (FFmpeg takes the rest of the text as one value) and a
   backslash at the end.
3. **The rules for a text**: it must parse; one chain only (no `;`); no link labels (they can
   reach other inputs in `-filter_complex`); every filter it names on the allow-list. A text
   that goes after a filter's `=` (a `custom` preset) must also not end that filter's
   options: no `,`, `;`, `[` or `]` outside quotes and escapes, and no backslash at the end (it
   would escape the template's next `,`). The text is checked against every chain of the
   filter that has `{custom}`, in the chosen implementation or, with none chosen, in every
   implementation (which one runs depends on the FFmpeg build); the preset and tune are not
   followed, so leftover text of a preset that does not use it is checked too (when in doubt,
   refuse). So a custom colorspace text needs `implementation: "zscale"` in web mode, since
   the libplacebo chain is not allowed.
4. **The allow-list** (`filtertext.ALLOWED_FILTERS`, 107 video filters): the filters of the
   definitions except `libplacebo` (its `lut`, `shader_cache`, `custom_shader_path` and
   `extra_opts` name files or pass unchecked options), plus common video filters with one
   input and one output. Each was checked with `ffmpeg -h filter=<name>` on the pinned build
   (and the Arch package): every option of type `string`, `dictionary` or `binary` was read,
   and a filter with any option that names a file, a directory, a URL, a network address, a
   device, a font, a model, a shader, a plugin or a codec is left out — for example `curves`
   (`psfile`, and `plot` writes), `nnedi` (`weights`), `deshake` (writes `filename`),
   `uspp` (`codec`), `drawtext`, `metadata`, `lut3d`, `zmq`, `frei0r`, `hwupload`. Also left
   out: source filters (no input), filters with a second input (`hysteresis`, `bm3d`,
   `haldclut`) and hardware filters (they need a device). No audio filter: free text reaches
   only the video graph. A test runs `-h filter=` on every entry and fails when an option
   that names a file appears (it also checks that the pattern finds the file options of
   `movie`, `drawtext`, `libplacebo` and `curves`). Expressions (`eq`, `lut`, `setpts`, …)
   use FFmpeg's evaluator, which reads no files.

### Consequences

- In web mode a client cannot read a file or load a plugin through free filter text; a
  chain of allowed filters still runs (a test renders a preview frame with one).
- A useful filter that is missing can be added after the same check of its options.
- A job stored in the queue before (for example by a desktop-mode server on the same data
  folder) is not checked again when a web-mode server runs it.
- Presets are not checked when they are saved: a preset does not run FFmpeg, and a job made
  from it passes the jail before it runs.

### Plan changes

- [06](../plan/06-web-app.md) §S-1, path jail item: free filter text in web mode.
