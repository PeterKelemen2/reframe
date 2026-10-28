# 0058 — S-4: the static frontend, its cache rules, and where `static_dir` comes from

- Status: accepted
- Date: 2026-10-28
- Steps: S-4

## Context

[06 §S-4](../plan/06-web-app.md#s-4-static-frontend-and-spa-fallback) says: in web mode,
serve `frontend/dist` with immutable cache headers for hashed assets and `index.html` for
unknown non-API paths; in desktop mode, no static files. It has no "Done when", and the
[breakdown](../server-complete-breakdown.md) adds the criteria (cache headers, the fallback,
the `/api` 404, the security middleware, no path escape, the default `static_dir`).

The plan does not say:

- where `static_dir` comes from when it is not set. `ServerConfig.static_dir` is `None` by
  default, `reframe-server` has no `--static-dir` option (`REFRAME_STATIC_DIR` works), the
  wheel of `reframe-server` holds no frontend, and `frontend/dist` is a git-ignored build
  output;
- which files are "hashed". `npm run build:web` (Vite 8.3.4) writes:

  ```
  dist/index.html                   0.39 kB
  dist/assets/index-CG_STmqm.css    0.29 kB
  dist/assets/index-fUAY8jXh.js   341.24 kB
  ```

  Vite puts every file with a content hash into `build.assetsDir` (`assets`). Files from
  `public/` would go to the top of `dist/` without a hash (the frontend has no `public/` yet);
- what a missing file under `assets/` gets, or a method other than `GET`.

uvicorn does not remove dot segments, and it decodes `%2e%2e`, `%2f` and `%00` before the app
sees the path ([testdata/README.md](../../testdata/README.md), "Request paths that reach the
static files (S-4)").

## Decision

1. **`static_dir` has no implicit default.** `None` means no static files: the server is
   API only. A deployment sets it: the Docker image (S-6) sets `REFRAME_STATIC_DIR` to the
   folder its `node` stage built, and a bare-metal install sets it to the output of
   `npm run build:web`. Rejected:
   - `frontend/dist` found relative to the installed package: it works only in an editable
     checkout. There it can serve an old build without telling anyone, and in an installed
     wheel the path does not exist.
   - The build inside the wheel. This changes the package build, which the lead owns. It
     needs Node when the wheel is built and belongs with Q-5's release pipeline. It is
     proposed below.
2. **Where it runs.** `static.install` replaces the app router's `default` handler.
   Starlette calls it only when no route matched, not even partly (a wrong method on an API
   route stays 405), and no slash redirect applied. So every route of the API wins. The
   handler is inside the middleware: the `Host` check, the `Origin` check and the security
   headers (CSP included) apply to every static answer.
3. **No credentials.** Static files need no token and no session: the login page must load
   before the user has logged in.
4. **Cache rules.** A file under `assets/` gets `Cache-Control: public, max-age=31536000,
   immutable`. Every other file, and `index.html` given for an unknown path, gets
   `no-cache`. Starlette's `FileResponse` sends `ETag` and `Last-Modified`, but the server
   does not answer `304`: a revalidation sends `index.html` (391 bytes) again.
5. **Fallback.** A `GET` or `HEAD` of a path that is not a file in the folder gets
   `index.html`. Three exceptions get the JSON problem 404 that the API gives for an unknown
   path:
   - a path under `/api` (also `/api` itself; `/apiary` is a page path);
   - a missing file under `/assets/`. An old tab that asks for the previous build's hash
     after an upgrade gets 404, not HTML under a script's URL;
   - any other method.

   A WebSocket to a page path is closed, so uvicorn answers 403.
6. **The folder jail.** For each request, the path is joined to the resolved folder and
   resolved, with links followed. The result must be a regular file inside the resolved
   folder, or it is not found. A NUL gives "not found" (`ValueError`). Because the folder is
   resolved for each request, a deployment can swap a link to a new build without a restart.
   A link inside the folder to a file inside the folder is served.
7. **Media types.** `.js`, `.mjs`, `.css`, `.html`, `.svg`, `.json` and `.wasm` get a fixed
   type. Python's `mimetypes` reads the Windows registry, which can map `.js` to
   `text/plain`, and a browser refuses a module script with that type. Other files keep
   Python's guess.
8. **A folder without `index.html`** logs a warning at start-up, and every page path then
   gets the 404.
9. **Desktop mode** serves no static file, also when `static_dir` is set.

### Proposals for the lead (files outside S-4)

- `config.py` / `__main__.py`: a `--static-dir` option. Every other path setting of 06
  §S-0 has an option, and the systemd unit (S-6) could then name the folder on its command
  line.
- The package build (`packages/reframe-server/pyproject.toml`, Q-5): put a web build in the
  wheel as `reframe_server/frontend/` (a hatch build hook or a release step that copies
  `frontend/dist`). Then `static_dir = None` would mean that folder when it holds
  `index.html`. This is a few lines in `static.install` once the build makes the folder.
- Optional, `config.py`: refuse a `static_dir` that is not a folder with `index.html` (exit
  2) instead of the warning in item 8.

## Consequences

- S-6 (task D): the image sets `REFRAME_STATIC_DIR`; `docs/deployment.md` tells a bare-metal
  user to build the frontend and set the variable (or the option, if the lead adds it).
- A file that Vite copies from `public/` must not go into `assets/`, because there it would
  be cached as immutable without a hash.
- A reverse proxy must serve Reframe at the site root: the server has no root-path setting,
  and the built `index.html` names `/assets/…` from the root. A sub-path would need both a
  root path in the server and Vite's `base` in the frontend.
- Windows: the `\` separator and drive letters are rejected by the same resolve-and-compare
  rule, but this is not run on Windows (decision 0053). The media-type table is tested on
  Linux with Python's guess patched to `text/plain`.

## Plan changes

- [06 §S-4](../plan/06-web-app.md#s-4-static-frontend-and-spa-fallback): both items ticked,
  with the default, the cache and fallback rules, and a link to this record.
- `docs/status.md`: the S-4 row.

## Follow-up (review), 2026-10-28

An independent review of S-4 found two defects: F1 (a blocker on Windows) and F3 (minor).

### F1: a request path that Windows reads as a UNC, drive or device path

**Finding.** The handler removed the leading `/` from the path and joined the rest to the
resolved folder, then resolved the result. uvicorn decodes `%5c` to `\`, so
`GET /%5c%5chost%5cshare%5cx.js` gives `\\host\share\x.js` (and `/%5c/host/share/x.js` gives
the same UNC path). On Windows the join drops the folder for an absolute path (a UNC path, a
drive path such as `C:/Windows/win.ini`, a device path such as `\\.\pipe\name`).
`Path.resolve()` then runs `ntpath.realpath`, which calls `nt._getfinalpathname` and so opens
the path: an SMB session to that host with the server user's NTLM credentials, from an
anonymous request. The containment check ran only after this. So item 6 and the Windows line
in "Consequences" were wrong: the resolve-and-compare rule refuses such a path, but only after
the OS has opened it. The facts are in [testdata/README.md](../../testdata/README.md), "Request
paths that reach the static files (S-4)".

**Fix (`static.py`).** Before any file-system call, the lookup refuses a path (not found) that
holds `\` or `:`, or that `ntpath.isreserved` calls reserved: a control character (NUL among
them), `"*<>?|`, a trailing dot or space, or a DOS device name (`CON`, `nul.txt`, `COM1`). The
same rule runs on every OS, so the Linux tests prove it. Without a leading `/`, a `\` or a `:`,
`PureWindowsPath` finds no drive and no root in the path. A Vite build has no such names. A
refused page path gets `index.html`, and a refused path under `/assets/` gets the problem 404,
like any other path that is not a file. A NUL no longer reaches `resolve()`, so the handler no
longer catches `ValueError`. It still catches `OSError`, which only `ntpath.realpath` raises.

**Test.** `test_windows_path_in_a_request_is_never_resolved` (rows `unc`, `drive`, `device`)
sends the request line to a live uvicorn, with `Path.resolve` patched to record its argument:
only the folder and its `index.html` are resolved, and the answer is `index.html` (or 404
under `/assets/`). On the old code all three rows failed: the recorded names held
`\\attacker.example\share\x.js`, `win.ini` and `COM1`. Not run on Windows (decision 0053).

### F3: a `static_dir` that holds the server's own files

**Finding.** A folder without `index.html` only logged a warning (item 8), and every file in
it was still served without a login. The review set `REFRAME_STATIC_DIR` to the parent of the
data folder: `GET /reframe/server.json` answered 200 with the token, and the token opened
`GET /api/queue`.

**Fix (`config.py`).** In web mode `ServerConfig` refuses a `static_dir` (a validation error,
so `reframe-server` exits 2 and prints the reason) when:

- it has no `index.html`. This replaces item 8 and does the optional proposal above;
- it is, or holds, the config, data or cache folder, or the endpoint file when
  `endpoint_file` is set. The endpoint file holds the token; its default is in the data folder.
  Both sides are resolved (links followed). A folder that the config does not set comes from
  `reframe.paths`, as the facade gets it (the server gives the facade no cache folder, so that
  is always `paths.cache_dir()`);
- it is, or holds, a media root or an output root (each one of the list is checked). Their
  files are not the server's own, but the API shows them only after a login, and the static
  files need none. Added at the lead's request after the first report.

Desktop mode serves no static file and checks no folder. A folder inside a server folder
(`<data>/web`) is allowed: only that folder is served. A link that is swapped after start-up is
not checked again.

**Tests.** `test_folder_without_index_html_is_refused`;
`test_folder_that_holds_a_server_folder_is_refused`, with `static_dir` through a link and one
row each: the config folder equal to the build, the data folder from `REFRAME_DATA_DIR` one
level below it (the review's layout), the cache folder through a second link, the endpoint
file, a media root inside the build as the second of two roots, and an output root equal to
the build as the second of two; and the desktop row of
`test_no_static_file_or_folder_check_without_web_mode_and_folder`, now with a folder without
`index.html`. On the old code the first two failed with `DID NOT RAISE`; the media and output
rows failed in the same way before their check was added. The real `reframe-server` with the review's layout exits 2 with
`reframe-server: Value error, static_dir … has no index.html`; with an `index.html` added to
that folder, it exits 2 with `… holds the config folder …: every file in it would be served
without a login`, and no `server.json` is written.

`test_deploy.py` builds a `ServerConfig` from the image's variables. The image's
`/opt/reframe/frontend` exists only in the image, so the test now checks that the variable
names the folder of the `frontend` stage, then points it at a temporary build.

**Not changed.** These review notes are accepted as they are: the cache rule uses the resolved
file and not the request path, the `startswith("assets")` detail, and the duplicate
`..` / `%2e%2e` test row.
