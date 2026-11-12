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

The results and the host tests are in [0002](0002-bundled-ffmpeg.md); this section is what the
other tasks need.

**Built.** `tools/bundled-tools.toml` (MKVToolNix 103.0 portable zip, only `mkvpropedit.exe`
and its licence files; MediaInfo CLI 26.10 zip, `MediaInfo.exe` and its licence files; both
`windows-x64` only). `scripts/bundle-tools.py` (reuses `reframe.tools.fetch`: download with
the size limit, `verify_file`, `safe_extract`, the tree digest of the marker); `fetch.py`
extracts a zip without a top folder. Tests: `testing/tests/test_bundle_tools.py`, three tests
in `packages/reframe/tests/tools/test_fetch.py`. The FFmpeg pin does not change.

**The CI step** (the S task's job, and the L task's Docker build in `ubuntu:22.04`), after
`uv sync --frozen`:

```sh
uv run python scripts/bundle-tools.py --platform linux-x64     # on Linux
uv run python scripts/bundle-tools.py --platform windows-x64   # on Windows (or on Linux)
```

The Linux layout builds libva from its pinned source (0002 "Follow-up"), so the Linux job or
image also needs `apt install meson ninja-build pkg-config gcc libdrm-dev` (the script names
what is missing), and it must run on `ubuntu:22.04`: the built libva needs that glibc (2.34 at
most there); built on a newer distro it would not load on 22.04.

It exits 1 with the reason on stderr (a checksum, a download, a foreign file in the folder,
a tool that discovery does not find as `bundled` with its pinned version). Its downloads can
be cached keyed on `tools/ffmpeg.toml` and `tools/bundled-tools.toml` (cache the archives, not
`resources/tools/`: the script re-hashes the folder anyway). The Linux layout needs a Linux
host (the tarball has symbolic links); the Windows layout builds on either. On a Windows whose
root store lacks mediaarea.net's root the MediaInfo download fails with
`CERTIFICATE_VERIFY_FAILED`; then run it with `SSL_CERT_FILE` set to the output of
`uv run python -m certifi` (needed on the VM; the GitHub runner is not checked).

**For L (packages)**: the `.deb` / `.rpm` get the tools in `/usr/lib/Reframe/tools/` (Tauri's
resource folder; the core finds it next to the sidecar), not 02's `/usr/lib/reframe/tools/`
(plan corrected). The licence files are `tools/ffmpeg/LICENSE.txt`,
`tools/mkvtoolnix/doc/COPYING.txt` (+ `README.txt`), `tools/mediainfo/LICENSE`
(+ `License.html`), `tools/ffmpeg/LICENSE-libva.txt` (MIT, Linux); the source links are in the two manifests (`source_commit`,
`build_scripts_commit`; `source_url`, `source_repository`, `source_tag`; libva:
`[libraries.libva]` `url`, `source_repository`, `source_tag`). The FFmpeg folder is
the archive root as it is (234 MB on Linux, `ffplay` and the headers included).

**Plan changes (in the same commit as 0002)**: 07 §D-7 bullet 2 said `resources/tools/<os>/`,
but one build makes one platform's package, so the layout is `resources/tools/` per build;
07 §Tool bundling and 02 §Bundled FFmpeg named `/usr/lib/reframe/tools/ffmpeg/` for the
`.deb` / `.rpm`, but Tauri installs resources under `/usr/lib/<productName>/`; 02 notes that
the build's VAAPI needs a newer libva than the oldest distros have, so the Linux layout ships
one (T2). 07 §D-7 bullet 1 is ticked; bullet 2 waits for
the CI job (S).

**Found for the lead and the owner**: with the system's libva, VAAPI was unavailable on Ubuntu
22.04 / 24.04 and Debian 12 (their libva lacks `vaMapBuffer2`, their FFmpeg is older than
Reframe's minimum). T2 ships libva 2.24.1 in the Linux layout: VAAPI then works wherever the
distro's Mesa can encode the codec (0002 "Follow-up": all three on Ubuntu 24.04, Debian 13 and
this host; on Ubuntu 22.04 and Debian 12 hevc only, as with their own FFmpeg). The libva pin
must follow libva releases (a driver built against a newer VA-API is not loaded). The Windows Detelecine crash stays (no build without it; one filter thread
does not avoid it). The `status.md` open items on the
Detelecine crash and on D-7's `LIBVA_DRIVERS_PATH` are answered by 0002 (the lead's rows).

## Task U — Settings → Tools and the first-run check (D-7)

Built on `m10-hardening` fcd3637 (2026-11-12). M4's Settings → Tools and first-run screen
(0063 "Task L", "Task C") were made for a server without a bundled build; this adds what a
desktop app that ships its tools needs.

**What the client could not know.** `ToolInfo.fixes` carries "Use bundled …" only while a tool
fails, so with a working Settings override the UI could not tell whether a bundled build exists.
`ToolInfo` gets `bundled: bool` (default `false`): a bundled build of the tool's *family* exists
(0005 item 2: FFmpeg = ffmpeg and ffprobe; mkvpropedit and MediaInfo each alone), also while an
environment or Settings override is in use. `ToolInfo` is a runtime model (not persisted; the
capability cache key does not include it), so no schema version changes; `scripts/gen-api.sh`
regenerated `schema.d.ts`.

**Use bundled, per tool** (Settings → Tools):

1. When the tool's family has a bundled build, the row's reset button is **Use bundled** (in
   place of *Remove override*). It removes the Settings paths of the whole family in one patch
   (an ffprobe path left behind would still win over the bundled ffprobe), then finds the tools
   again. No download. It shows only when one of those paths is set, and never for a tool the
   environment sets (02 §Path override row 1; the row stays read-only with M4's note).
2. Without a bundled build, the rows keep *Remove override* and the section keeps M4's *Use
   bundled FFmpeg* (download the pinned build, then remove the paths). With a bundled FFmpeg the
   section button is gone: there is nothing to download.
3. The first-run screen's *Use bundled FFmpeg* follows the same rule (`useBundledTools`, shared
   by both screens). With a bundled FFmpeg but no Settings path to remove (the bundled build
   itself is damaged) it is not offered: neither a reset nor a download into
   `<data dir>/tools` (searched after `<exe dir>/../tools`) would change the result; the reason
   says to reinstall. A refused settings change now shows on the first-run screen too (M4 dropped
   it silently there).
4. A broken override is still never replaced without the user: *Use bundled* is a click.

**The first-run check before the main UI.** In the desktop app (`platform.kind === 'desktop'`),
the first start shows the first-run screen in place of the workspace once `GET /api/system` has
answered (the boot waits for tool discovery before phase `ready`), also when every tool works:
"Welcome to Reframe", each of the four tools with status, origin, path and version, *Continue*,
*Open Settings → Tools*, *Check again*. While FFmpeg fails it is M4's screen (with all four tools
on the first start) and has no *Continue*; once FFmpeg works, *Continue* appears. After
*Continue* the screen comes back only while FFmpeg has a problem (M4's rule). The web app is
unchanged (M4's rule only).

**Where "the first start has been seen" is stored: the webview's `localStorage`**
(`reframe.firstRun.seen`, VueUse `useLocalStorage`). Simplest correct: the flag belongs to this
desktop app on this computer, not to the server's settings (a server's `settings.json` can be
shared by a web front end, and a new persisted field would touch `AppSettings` and the
persistence rules for a value only the desktop UI reads) nor to the Rust shell's `desktop.json`
(a new command for one boolean). Losing it (cleared webview data) shows the tools once more,
which is harmless. Checked in the real app: WebKitGTK keeps it in
`$XDG_DATA_HOME/org.reframe.desktop/localstorage/tauri_localhost_0.localstorage`, and a second
start goes straight to the workspace. On Windows WebView2 keeps it in its user data folder (not
verified).

**Checked in the real app** (2026-11-12, this host, the debug build of 933dc22 with its frozen
sidecar, copied with `.cargo-lock` into `scratchpad/task-u/target/debug/`, the pinned FFmpeg
n9.0.2 build folder copied as `target/debug/tools/ffmpeg/`; virtual KWin socket `reframe-u`,
private `XDG_*` and `REFRAME_*_DIR`, `REFRAME_POWER_DRY_RUN=1`, the inspector on 8729, light and
dark screenshots):

- First start: the welcome screen; ffmpeg and ffprobe "Found", "Bundled with Reframe",
  `…/target/debug/tools/ffmpeg/bin/ffmpeg`, version `n9.0.2-17-g2a571b6068-20260930`;
  mkvpropedit from `PATH` (`/usr/bin/mkvpropedit`, 103.0); mediainfo missing (optional, warn).
  *Continue* showed the workspace with the focus on *Open files…* and stored the flag.
- Second start (same folders): straight to the workspace.
- Settings → Tools: `/usr/bin/ffmpeg` in the ffmpeg field and *Test*: "Works: version n9.0.2",
  origin "Path in the settings", ffprobe "Path in the settings (next to ffmpeg)", both rows with
  *Use bundled*, no section download button. *Use bundled* sent only `PUT /api/settings` and
  `POST /api/system/tools/rescan` (no `tools/fetch`; no `<data dir>/tools` folder), both tools
  "Bundled with Reframe" again, the settings file's tool paths all `null`.
- `/nonexistent/ffmpeg` as the override: the workspace shows "FFmpeg cannot be used" with the
  reason; its *Use bundled FFmpeg* sent the same two requests and the workspace came back.
- `REFRAME_FFMPEG=/usr/bin/ffmpeg`: the ffmpeg row read-only with the variable's note, no *Use
  bundled* and no *Remove override* (ffprobe found next to it keeps an editable field, M4).
- The web app (`scripts/dev-server.py` on 8720, `build:web`, headless Chromium): the workspace at
  once (no first-run screen), every path read-only, M4's *Use bundled FFmpeg* download button.

**Not verified (Windows, for task W or the lead on the VM):** a bundled `mkvtoolnix/` and
`mediainfo/` from task T's layout: each row should show "Bundled with Reframe"; a Settings path
on mkvpropedit or mediainfo should give that row alone *Use bundled* (the other rows unchanged),
and the click should send only the settings patch and the rescan; the first start's welcome
screen listing all four as bundled; the flag surviving a restart in WebView2.

**Seen, not changed** (M4 behaviour): an ffprobe found next to an ffmpeg set by
`REFRAME_FFMPEG` shows "Environment variable REFRAME_FFPROBE (next to ffmpeg)", naming a variable
that is not set. A file opened from argv on the first start opens behind the welcome screen and
shows after *Continue*; `Ctrl+O` on the welcome screen opens the file dialog the same way (`useShortcuts` blocks it
only while FFmpeg fails; read from the code, not tried).

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
