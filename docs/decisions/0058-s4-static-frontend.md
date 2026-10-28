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
