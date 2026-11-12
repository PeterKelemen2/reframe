# 0072 — M10: tool bundling, packaging, updater and smoke tests

- Status: accepted
- Date: 2026-11-12
- Steps: D-7, D-8, D-9, Q-3, Q-1.4

## Context

The rest of M10 that the Windows test VM (libvirt `win10`: Windows 10 Pro 22H2 19045, 6 logical
processors, 8 GB, no GPU) makes possible: D-7 (the bundled tools and Settings → Tools), D-8
(installers, packages, updater, licence notices) and D-9 (the `tauri-driver` smoke tests), each
with its Linux and its Windows half, and the Windows checks of Part 1 (the CI commands on 22H2,
the cold start again, the "Not verified" leftovers). Who builds what is in
[m10-breakdown.md](../m10-breakdown.md). D-7's host results are in
[0002](0002-bundled-ffmpeg.md).

The owner's answers (2026-11-12):

1. **Signing**: Windows installers are signed with a self-signed test certificate made on the
   VM (its private key stays there). The updater's test key pair is generated outside the
   repository, in `~/.config/reframe-test-keys/` on the host. Real signing with a bought
   certificate is out of scope.
2. **The Windows FFmpeg build**: try another Windows build against the `fieldmatch` crash of
   BtbN n9.0.2 win64 ([0070](0070-windows-testing-phase.md) "The desktop part"); switch the
   `windows-x64` pin if it is clean and meets 02 §Bundled FFmpeg.
3. The owner checks at the VM window when asked; one display head, so two monitors stay not
   verified.
4. NSIS, WiX, `tauri-driver` and `msedgedriver` may be installed on the VM; Docker containers may
   run on the host.

## Decision

1. **The bundled tools** are laid out by `scripts/bundle-tools.py` in
   `desktop/src-tauri/resources/tools/` and shipped as `<resources>/tools/` next to
   `<resources>/sidecar/` ([0005](0005-tool-discovery-details.md) item 2's layout; the core
   already searches `<exe dir>/../tools`). `bundle.active` is on; the bundle targets are per
   platform (`tauri.linux.conf.json`, `tauri.windows.conf.json`).
2. **The oldest supported Linux distro is Ubuntu 22.04 LTS** (glibc 2.35, the first Ubuntu with
   `libwebkit2gtk-4.1`, which Tauri 2 needs). The plan did not name one; the AppImage and the
   `.deb` are built in its image.

## Part 1 — the VM checks (lead)

**The CI commands and the whole suite on 22H2** (2026-11-12, `m10-hardening` 3a5a2cb, the VM's
clone in Git Bash over SSH; FFmpeg n9.0.2 as the bundled build in `%LOCALAPPDATA%\Reframe\tools`,
not on `PATH`; MKVToolNix 103.0 and MediaInfo CLI 26.10 on `PATH`): `uv lock --check`,
`uv sync --frozen`, `python -m reframe.tools --require ffmpeg,ffprobe --expect-origin bundled`,
ruff, ruff format (542 files), mypy and `mypy --platform linux` (540 files), the test media
(16 up to date); every frontend command (`npm ci`, lint, fmt:check, typecheck, `npm test` 1940
passed, build:web, build:desktop); the Rust job (`cargo fmt --check`, clippy `-D warnings`,
`cargo test` 24 passed). The whole `uv run pytest` with `REFRAME_REQUIRE_FFMPEG=1` (also the
`needs_gpu` and `benchmark` tests): **7481 passed, 3 failed, 204 skipped in 23 min**. The three
failures are `needs_gpu` tests, which CI's selection leaves out:

- `capabilities/test_real.py::test_every_hardware_encoder_gets_a_final_state` and
  `preview/test_frames.py::test_hdr_frames_with_libplacebo`: they need a GPU (expected).
- `capabilities/test_real.py::test_libplacebo_without_a_vulkan_driver`: **a wrong reason.** The
  VM's Vulkan loader reports instance API 1.0.0; libplacebo says `Instance API version 1.0.0 is
  lower than the minimum required version of 1.2.0, cannot proceed!`, which Reframe's reason
  table does not know, so libplacebo is `error` instead of `unavailable`. Fixed in task T.

**Q-3, the desktop cold start again**: the release build of 096836f with its frozen sidecar,
measured as 0070 did: **median 1.38 s, worst 1.43 s** (10 runs; the first run after the build
2.66 s); the frozen sidecar alone is ready in 0.96–1.03 s. The budget is met on this VM; the
4.7 s of 0071 was the laptop VM's CPU ([0071](0071-server-start-and-windows-cold-start.md)
"Follow-up").

**The "Not verified" Windows leftovers that need no second user** (2026-11-12, the release build
of 096836f in the owner's logged-on console session, started by a scheduled task, read over
WebView2's DevTools port; clicks with `SetCursorPos` + `mouse_event` and screenshots of the
whole screen from a task in the same session):

- **Theme follow: passes.** With Appearance → Theme *System* (the default), setting
  `HKCU\…\Themes\Personalize\AppsUseLightTheme` to 0 while the app runs turned the page dark
  (`prefers-color-scheme: dark` true, the `reframe-dark` class) and the native title bar dark
  within 3 s; 1 turned both light again. No restart, no code: WebView2 and Tauri follow the
  setting.
- **The tray menu: passes.** Tray switched on (Settings → Desktop's command). Windows puts a new
  icon in the hidden-icons panel. Its menu: the progress line (disabled; *No job is running*,
  *Queue: 15 %* while a CLI's job ran), **Pause all**, **Show Reframe**, **Quit**. With a running
  job, closing the window asked *Quit Reframe? 1 job is running or paused* with **Keep running in
  tray**, which hid the window and kept the job running; **Pause all** paused the job (19.5 %,
  `reframe queue list`); **Show Reframe** brought the window back (*Queue: 1 paused*); **Quit**
  showed the same dialog, and **Stop jobs and quit** ended the app, the sidecar and FFmpeg, left
  no `.part`, and the job `interrupted`. With no job, closing the window quits at once (0069's
  design: the tray keeps the app only through the dialog's button).
- Seen on the way: the app's icon is a placeholder (a blue square; `icons/icon.png` is 104
  bytes). The lead makes a real icon set for the packages (D-8).

## Task T — the bundled tools (D-7)

*Placeholder: filled by task T.*

## Task U — Settings → Tools and the first-run check (D-7)

*Placeholder: filled by task U.*

## Task L — Linux packages and licence notices (D-8)

*Placeholder: filled by task L.*

## Task W — Windows installers and the updater (D-8)

*Placeholder: filled by task W.*

## Task S — the smoke tests (D-9)

*Placeholder: filled by task S.*

## Review and fix round

*Placeholder: filled by the lead.*

## Consequences

*Filled at the end.*

## Plan changes

*Filled at the end.*
