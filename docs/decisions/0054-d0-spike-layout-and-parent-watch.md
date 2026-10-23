# 0054 — D-0 spike layout, its checks, and the server's parent watch

- Status: accepted
- Date: 2026-10-23
- Steps: D-0, S-0

## Context

D-0 ([07 §D-0](../plan/07-desktop-app.md#d-0-spike-do-this-before-the-frontend-is-far-along))
is a spike: a minimal Tauri 2 app, a PyInstaller onedir build of `reframe-server` as its
sidecar, measurements, and WebKitGTK checks. The plan does not say where the spike code
lives, whether it is committed, or how its code is checked. D-1 makes `desktop/src-tauri/`
and D-2 makes `desktop/sidecar/build.py`, so the spike must not take those paths.

[07 §Sidecar lifecycle](../plan/07-desktop-app.md#sidecar-lifecycle) starts the sidecar with
`--parent-pid <pid>`, and on Linux "the server watches `--parent-pid` and exits when the parent
is gone". D-0 must prove that cleanup. But [06 §S-0](../plan/06-web-app.md#s-0-package-skeleton)
has no `--parent-pid`, and `reframe-server` does not have it:

```
$ grep -rn 'parent' packages/reframe-server/src
$
```

The machine for the spike (checked 2026-10-23): CachyOS, KDE Plasma on Wayland, Intel UHD 620,
NVMe SSD; rustc / cargo 1.99.1 stable; WebKitGTK `webkit2gtk-4.1` 2.54.1, libsoup 3.8.0,
GTK 3.24.52, librsvg 2.63.3, OpenSSL 3.6.5, xdotool. The Tauri 2 prerequisites page lists
`libappindicator-gtk3` for Arch. That package name no longer exists in the Arch repositories
(`pacman -Si libappindicator-gtk3`: not found; the package is now `libappindicator`), and
`libayatana-appindicator` 0.6.1 is installed. The spike has no tray, so this does not block
D-0. D-6 (tray) checks it again. No Chromium is installed; `sudo` needs a password.

## Decision

1. **The spike lives in `desktop/spike/` and is committed**, so that the measurements can be
   reproduced. CI does not build it. D-1 and D-2 may reuse its code or delete the folder.
   Layout:
   - `desktop/spike/src-tauri/`: the Tauri 2 app (`Cargo.toml`, `Cargo.lock`,
     `tauri.conf.json`, `capabilities/`, `src/`).
   - `desktop/spike/ui/`: the spike pages (Vite + Vue). They are not F-x components.
   - `desktop/spike/package.json` + `package-lock.json`: `@tauri-apps/cli`,
     `@tauri-apps/api`, and the UI's build tools. Vue, PrimeVue and `@primeuix/themes` use
     the same versions as `frontend/package-lock.json`, so the WebKitGTK checks see the
     versions the UI will use.
   - `desktop/spike/scripts/`: the Python of the spike (the sidecar build, the measurement
     scripts).
   - `desktop/spike/README.md`: how to build and run it, and how to repeat each measurement.
   - Build output stays out of git: `desktop/spike/src-tauri/target/`,
     `desktop/spike/src-tauri/gen/`, and the PyInstaller `build/` and `dist/` folders (the
     existing `build/` and `dist/` patterns of `.gitignore`).
2. **How the spike is checked.** The Python in `desktop/spike/scripts/` follows the same rules
   as `scripts/`: `ruff check`, `ruff format --check` and strict `mypy` run on it (the
   `desktop` exclusion in ruff's configuration is narrowed to `desktop/spike/src-tauri` and
   `desktop/spike/ui`, and mypy's `files` gets `desktop/spike/scripts`). The Rust code is
   checked by the spike's author and by the lead before a merge with `cargo fmt --check` and
   `cargo clippy --all-targets -- -D warnings`; CI does not run them, because CI does not
   build the spike. The spike's UI is checked by its production build (`vite build`); it is
   not linted. D-1 decides the checks for the real app.
3. **Versions** (current stable on 2026-10-23): crates `tauri` 2.12.5 and `tauri-build` 2.7.4,
   with `Cargo.lock` committed; npm `@tauri-apps/cli` 2.12.4 and `@tauri-apps/api` 2.12.4,
   with `package-lock.json` committed; PrimeVue 4.5.5, `@primeuix/themes` 2.0.3, Vue 3.5.43,
   Vite 8.3.4 (the frontend's pins); PyInstaller 6.22.3 as a dev dependency of the workspace
   (`pyinstaller>=6.22.3` in the root `dev` group, pinned in `uv.lock`). The spike does not
   use `tauri-plugin-shell`: it spawns the sidecar with `std::process` / `tokio::process`, as
   D-3 will, so it can set the child's death signal.
4. **`--parent-pid` is part of S-0.** `ServerConfig.parent_pid` (`REFRAME_PARENT_PID`; `None`
   by default) and `reframe-server --parent-pid PID`. When it is set, the server watches that
   process and, when it ends, stops the way `POST /api/system/shutdown` does (the queue
   cancels its jobs, the facade closes), with a hard exit if the stop does not end in time.
   The watch must not take a reused pid for the parent. On Linux the desktop shell also gives
   the sidecar a death signal (`PR_SET_PDEATHSIG` in `pre_exec`): the parent watch is the
   second line, for a parent that is not the direct parent and for the platforms without a
   death signal. The Windows path of the watch is written and mock-tested on Linux
   ([0053](0053-linux-first-windows-testing-phase.md)).

## Consequences

- The spike is reproducible from the repository, and nothing in CI depends on it.
- The spike's Rust and UI code are checked by hand only. That is acceptable for code that D-1
  may delete; it is not acceptable for `desktop/src-tauri/` (D-1 decides).
- PyInstaller is installed by `uv sync` on every machine, also in CI, where it is not used.
- The parent watch is server code with tests in CI; the desktop shell of D-3 relies on it.

## Plan changes

- [06 §S-0](../plan/06-web-app.md#s-0-package-skeleton): `parent_pid` in `ServerConfig`, the
  `--parent-pid` option and the watch.
- [07 §D-0](../plan/07-desktop-app.md#d-0-spike-do-this-before-the-frontend-is-far-along):
  where the spike lives.
- [../m3-breakdown.md](../m3-breakdown.md): waves 4 to 6.
