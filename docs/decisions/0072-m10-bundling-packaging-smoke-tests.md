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
must follow libva releases (a driver built against a newer VA-API is not loaded).
T2 also gives every tool and user-facing program that the frozen app starts the user's
environment (`reframe.platform.childproc.user_environ`, used by `reframe.tools.run`,
`launch_detached` and the owner start in `reframe.remote.owner`; `childproc.py` and `owner.py`
are outside T's file list, the lead gave T the tools' environment handling): PyInstaller's `LD_LIBRARY_PATH` and the AppImage's `$APPDIR` entries broke
`mkvpropedit`, VAAPI, AMF and libplacebo inside L's AppImage on this host (0002 "Follow-up"). The Windows Detelecine crash stays (no build without it; one filter thread
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

Built and checked 2026-11-12 on the AMD desktop (CachyOS, Docker 29.9.2 with the classic
builder, KWin 6.8 for the virtual session), Tauri CLI 2.12.4.

**The build** (`desktop/packaging/linux/`): `Dockerfile` is `ubuntu:22.04` (pinned by digest)
with Tauri's Linux build packages, Node 24.22.1 and rustup 1.29.3 (both checked by SHA-256),
Rust 1.99.1, uv 0.13.5 with CPython 3.14.8, `cargo-about` 0.9.3 (only for the notices), and
`meson`, `ninja-build` and `libdrm-dev` for task T's libva build.
`build.sh OUT` builds the image and pipes the working tree's tracked and untracked files (not the
ignored ones) into a container that runs `build-in-container.sh`: `uv sync --frozen`, the tools
layout, the frozen sidecar, `npm ci`, the notices, `npx tauri build --verbose` (the targets of
`tauri.linux.conf.json`), then the three packages, `THIRD_PARTY_NOTICES` and `glibc.txt` to
`OUT`. Cargo's registry, the target folder and the download caches are volumes
(`$REFRAME_BUILD_NAME-{cargo,target,cache}`). A release job runs, from the repository root:

```sh
desktop/packaging/linux/build.sh dist/linux            # AppImage, .deb, .rpm, notices, glibc.txt
desktop/packaging/linux/install-test.sh dist/linux     # ubuntu:22.04, debian:12, fedora:45
desktop/packaging/linux/appimage-test.sh dist/linux/Reframe_0.1.0_amd64.AppImage  # needs KWin
```

The tools layout is one line of `build-in-container.sh`: `bundle-tools.py --platform linux-x64`
(before task T merged, `fetch-tools.py --install-dir` gave the same `ffmpeg/` folder).

**What the Tauri bundler and linuxdeploy do with the bundled FFmpeg** (checked):

1. **The bundler copies a symbolic link in `bundle.resources` as one more copy of its target.**
   The archive's `lib/` names each library three times (`libavcodec.so`, `libavcodec.so.63` →
   `libavcodec.so.63.1.102`): the first `.deb` and `.rpm` were 327 MB (`libavcodec`, 120 MB,
   three times). The build deletes the links and renames each library to its soname
   (`readelf -d`), the name the programs ask the loader for: 153 MiB each.
2. **linuxdeploy fails on libraries that find each other only through the program's RPATH**
   (`ffmpeg` has `RPATH $ORIGIN/../lib`; `libswscale.so.10` has none): `ERROR: Could not find
   dependency: libavutil.so.61`. With `LD_LIBRARY_PATH` set to that folder it succeeds but copies
   all seven FFmpeg libraries a second time into the AppImage's `usr/lib/`.
   `LINUXDEPLOY_EXCLUDED_LIBRARIES` (a `;`-separated list that linuxdeploy 07333c6 reads: found
   in its strings, then tried) with the bundled libraries' names avoids both; the build sets it.
3. **linuxdeploy rewrites the ELF files already in the AppDir**: `ffmpeg`'s
   `RPATH $ORIGIN/../lib` becomes `RUNPATH $ORIGIN/../lib:$ORIGIN`, and the frozen
   `reframe-server` changes (its SHA-256 differs). Both still run (the AppImage checks below).
4. Tauri downloads `linuxdeploy-07333c6`, `linuxdeploy-plugin-appimage` (continuous) and its
   `AppRun` from GitHub during the build; this repository pins none of them.

**glibc** (`glibc-report.sh`: the newest `GLIBC_` version in `objdump -T` of every ELF file in the
AppImage, the sidecar's `_internal/` included): the newest is **`GLIBC_2.35`**, needed by
`sidecar/_internal/libgcc_s.so.1`, `libwebkit2gtk-4.1.so.0`, `libjavascriptcoregtk-4.1.so.0` and
`libcairo.so.2` (Ubuntu 22.04's own libraries); `reframe-desktop` needs 2.34, the FFmpeg build
2.28, the AppImage runtime nothing (static).

**The packages** (`tauri.linux.conf.json`, `linux/`):

- **Install location: the plan was wrong.** Tauri puts the resources in `/usr/lib/<productName>/`,
  so FFmpeg is in `/usr/lib/Reframe/tools/ffmpeg/`, next to `/usr/lib/Reframe/sidecar/`; the
  frozen programs find it as `<exe dir>/../tools` (the CLI through `/usr/bin/reframe` too:
  PyInstaller resolves the link). 02 §Bundled FFmpeg and 07 §Tool bundling now say (task T found the same)
  `/usr/lib/Reframe/`. The core's `/usr/lib/reframe/tools` root stays (no code change).
- `.deb` `Depends: libayatana-appindicator3-1, libwebkit2gtk-4.1-0, libgtk-3-0` (Tauri's),
  `Recommends: mkvtoolnix, mediainfo`; the `.rpm` requires the three sonames and recommends
  `mkvtoolnix` and `mediainfo` (rpm's weak dependency, which dnf installs). Neither names FFmpeg.
- **The desktop entry** comes from `linux/Reframe.desktop.hbs` (Tauri's own template with
  `Exec={{exec}} %F` and `Categories=AudioVideo;Video;`): `Reframe.desktop`,
  `StartupWMClass=reframe-desktop`, the `MimeType=` of the file associations;
  `desktop-file-validate` passes.
- **The `.rpm` left its folders behind**: the bundler's spec owns the files under
  `/usr/lib/Reframe/` but not the folders, so `dnf remove` left the empty tree (checked).
  `linux/remove-app-dirs.sh` is the `.rpm`'s `postRemoveScript`: on an erase (`0`) it removes
  the empty folders under `/usr/lib/Reframe` (a file that the package did not install stays).
  dpkg removes its folders itself.
- `link-cli.sh` and `unlink-cli.sh` run as 0069 wrote them: `/usr/bin/reframe` →
  `/usr/lib/Reframe/sidecar/reframe` after install, gone after removal, with apt and dnf.
- **The AppImage** carries FFmpeg (`usr/lib/Reframe/tools/ffmpeg/`); the CLI is not on `PATH`
  (no install step); mkvpropedit and MediaInfo come from the system. linuxdeploy copies the
  copyright files of the 102 distro packages whose libraries it bundles into `usr/share/doc/`.
  It leaves the libraries of the AppImage exclude list to the host: a bare `debian:12` needed
  `libdrm2 libegl1 libexpat1 libfontconfig1 libfreetype6 libfribidi0 libgbm1 libgl1
  libharfbuzz0b libwayland-client0 libx11-6 libx11-xcb1 libxcb1` (`ldd` in the extracted
  AppImage). Every desktop has them.

**Install tests** (`install-test.sh` runs `install-test-in-container.sh` in each image with the
packages and `testdata/media` mounted; last run 2026-11-12, all `PASS`): `ubuntu:22.04`
(22.04.5), `debian:12` and `fedora:45`: installed with `apt-get install ./….deb` /
`dnf install ./….rpm` (dependencies and recommends resolved; no `ffmpeg` package, no FFmpeg in
Depends/Requires); `/usr/bin/reframe` is the link; `notices/THIRD_PARTY_NOTICES` is there with
the FFmpeg source link; the desktop entry is valid with `%F`; `reframe version`;
`reframe tools status --json`: ffmpeg and ffprobe `bundled` at `/usr/lib/Reframe/tools/ffmpeg/bin/`
(n9.0.2-17-g2a571b6068-20260930); `reframe encode -p very-fast-1080p30` of `multitrack.mkv`
through the frozen server (341 512 bytes: h264, 3 × aac, 3 × mov_text); `reframe-desktop` under
Xvfb and `dbus-run-session`, with private `XDG_*` and `REFRAME_*_DIR` and
`REFRAME_POWER_DRY_RUN=1`: its sidecar `/usr/lib/Reframe/sidecar/reframe-server` publishes
`server.json` and answers `GET /api/system` (mode `desktop`, ffmpeg `bundled` at the installed
path); SIGTERM to the app ends the app and the sidecar; removal leaves no `/usr/bin/reframe`, no
`/usr/lib/Reframe`, no desktop entry. In `debian:12` another package's recommends bring the
distro's `libavcodec59` (not Reframe's; which package was not checked; the `ffmpeg` program is
not installed).

**The AppImage** (`appimage-test.sh`): on this host in `kwin_wayland --virtual` (socket
`reframe-l`, private folders, `REFRAME_POWER_DRY_RUN=1`) the AppImage mounts itself (FUSE), the
sidecar `/tmp/.mount_…/usr/lib/Reframe/sidecar/reframe-server` answers, ffmpeg is `bundled` at
`/tmp/.mount_…/usr/lib/Reframe/tools/ffmpeg/bin/ffmpeg`, and the screenshot shows the workspace;
SIGTERM to `reframe-desktop` ends the runtime, the webview and the sidecar. In `debian:12`
without `/dev/fuse`, `--appimage-extract-and-run` under Xvfb: the same from
`/tmp/appimage_extracted_…/`.

**A defect found, not fixed (core code, not this task's files): system tools run with the
sidecar's library path.** The frozen sidecar's `LD_LIBRARY_PATH` starts with its `_internal/`
(PyInstaller); in the AppImage it also holds the AppImage's library folders (its `AppRun` sets
them; PyInstaller keeps that value in `LD_LIBRARY_PATH_ORIG`). The core starts mkvpropedit and
mediainfo with it, so a system tool built against a newer `libstdc++` than Ubuntu 22.04's fails:

- Fedora 45 (`.rpm`): `mkvpropedit` `broken`: `/usr/lib/Reframe/sidecar/_internal/libstdc++.so.6:
  version 'CXXABI_1.3.15' not found (required by /lib64/libicui18n.so.78)`; `mediainfo` `broken`
  (`GLIBCXX_3.4.35`, required by `/lib64/libmediainfo.so.0`).
- The AppImage on this host: `mkvpropedit` `broken` the same way.
- Ubuntu 22.04 and Debian 12: both `found` (their `libstdc++` is not newer).

FFmpeg is not affected (its own libraries through its RPATH). The fix belongs in
`reframe.tools`: start external programs with PyInstaller's `LD_LIBRARY_PATH_ORIG` restored
(unset when there was none) and, when `APPIMAGE` / `APPDIR` are set, without the entries under
`$APPDIR`. Until then, 07's "System packages, if installed" holds only on distros as old as the
build image.

**`THIRD_PARTY_NOTICES`** (`scripts/third-party-notices.py --platform linux-x64|windows-x64`, run
by the build as `uv run --with pip-licenses==5.5.5 python scripts/third-party-notices.py …`, with
`npx` and `cargo about` on `PATH`): one text file in `desktop/src-tauri/resources/notices/`,
mapped to `notices/` in `bundle.resources`, so every Tauri artefact (the Windows ones too)
carries it. Sections:

- **Bundled tools**: one entry per folder in `resources/tools/` with every field of its pin
  (version, the platform's download URL and SHA-256, `source_repository`, `source_branch`,
  `source_commit`, `build_scripts_repository` / `_commit`, the release page) and the folder's
  licence file. A folder without a pin or a licence file stops the run. The pin is
  `[builds.default]` of `tools/<folder>.toml`, or `[tools.<folder>]` of another
  `tools/*.toml` (task T's `tools/bundled-tools.toml` for MKVToolNix and MediaInfo).
- **Python**: CPython's `LICENSE.txt`; the distributions whose modules are in the frozen
  executables' archives (read with PyInstaller's `CArchiveReader`) or in `_internal/`, mapped
  with `importlib.metadata.packages_distributions()`, without Reframe's own, plus PyInstaller
  (its bootloader is in every executable): 42 distributions through pip-licenses (licence and
  notice texts; `--with-system`, else it drops setuptools); and MediaInfoLib: pymediainfo's
  wheel carries `libmediainfo` 24.12 without its licence, so its BSD-2-Clause text is read from
  `MediaArea/MediaInfoLib` at the tag of the loaded version.
- **JavaScript**: `npx license-checker@25.0.1 --production --excludePrivatePackages` on
  `frontend/` (105 packages; the text of a file named like a licence, not the README that it
  sometimes names).
- **Rust**: `cargo about generate --format json --locked` with a generated config (the
  platform's target, no build or dev dependencies, the accepted licences of today's crates: a
  new licence stops the run until someone reads it and adds it). `cargo-about` 0.9.3 needs
  `--features cli`: without it `cargo install` installs nothing and exits 0.

The file is 958 KB. Found in it: the frozen sidecar ships `_pytest` and `setuptools` modules
(PyInstaller's analysis pulls them in), so pytest and setuptools are listed; license-checker's
production tree holds build-time packages of `vue` and `vue-router` (`@vue/compiler-*`, vite,
rolldown, typescript), listed though not all of them ship. **Not covered**: the libraries that
python-build-standalone links into CPython (OpenSSL, libffi, SQLite, ncurses and others: the
`LICENSE.txt` names only CPython), and ZenLib inside `libmediainfo`.

**The Docker image (S-6)** also bundles FFmpeg, but it ships the server's virtual environment
(not a frozen sidecar), the web frontend and no Rust: the script would need a mode that reads
the environment instead of `_internal/` and leaves Rust out, and the Dockerfile a stage with
Node and the script's tools. Not a one-line change: not done.

**Tests**: `testing/tests/test_third_party_notices.py` (18 tests: which distributions are listed;
the real frozen sidecar's archives (skipped without a build); pip-licenses' skipped package;
license-checker's README; cargo-about's own crate and target; each pin shape and the real
Windows manifest; a tool without a
pin or a licence; the MediaInfoLib URL for the loaded version; the rendering; the
`bundle.resources` entry) and `testing/tests/test_linux_packaging.py` (4: the template with `%F`
and the recommends of both packages; `remove-app-dirs.sh` on erase and upgrade). Each test
function failed under a mutation of the code it covers (27 mutations) and passed again after.

**For later tasks**: T: the bundler copies links, so the layout needs one file per library under
its soname; `include/`, `lib/pkgconfig/`, `man/` and `doc/` of the archive ship too. The build's
link step and `LINUXDEPLOY_EXCLUDED_LIBRARIES` work on whatever `resources/tools/*/lib/` holds.
W: the notices are in `notices/` of the NSIS/MSI install too (`--platform windows-x64` gives the
Windows crates and pins). The lead: the core fix above; `notices/.gitignore` (the folder's ignore
rule, inside the folder because the root `.gitignore` is the lead's) ships in the packages, as
`sidecar/README.md` does; Tauri installs `icons/128x128@2x.png` as
`usr/share/icons/hicolor/256x256@2/apps/reframe-desktop.png`, which is not an icon theme folder;
`reframe encode -p very-fast-1080p30 -o out.mkv` writes MP4 into the `.mkv` name.

## Task W — Windows installers and the updater (D-8)

Built and checked 2026-11-12 on the VM `win10` (22H2) in the owner's logged-on console session:
the scripts ran there through a scheduled task (`/IT`, the user's filtered token, as a user who
double-clicks), with clicks by `SetCursorPos` + `mouse_event`, UI Automation for the native
windows, WebView2's DevTools port where the page was read, and screenshots of the whole screen.
The bundles were built on the VM (`npx tauri build`, `CARGO_TARGET_DIR` shared) from the frozen
sidecar, `bundle-tools.py --platform windows-x64` (with `SSL_CERT_FILE` from `certifi`, as T
found) and `third-party-notices.py --platform windows-x64`.

**What the bundler does by itself** (Tauri CLI 2.12.4, bundler 2.10.4): it downloads and checks
NSIS 3.13, `nsis_tauri_utils` 0.5.3 and WiX 3.14.1 into `%LOCALAPPDATA%\tauri\` (nothing was
installed by hand). With a certificate in the config it signs `Reframe.exe`, the uninstaller,
both installers and **every unsigned `.exe` and `.dll` under `bundle.resources`**: the frozen
sidecar's executables and DLLs and the bundled FFmpeg (it writes the signatures into
`resources/` in place; MKVToolNix's and MediaInfo's executables are already signed by their
publishers and are left alone). So the sidecar needs no signing step of its own.

### The installers

1. **NSIS, per user** (`tauri.windows.conf.json`: `installMode` `currentUser`). Started from the
   user's filtered token, the installer and the installed app run unelevated (token elevation
   type 3) and no UAC prompt appears. **Defect found and fixed: the default folder.** Tauri's
   per-user default is `%LOCALAPPDATA%\Reframe`, which is Reframe's data folder (`platformdirs`:
   the queue, settings, logs, cache and `tools\`): the installer's `tools\ffmpeg\bin\` is exactly
   where *Use bundled FFmpeg* downloads the pinned build, so an install overwrote it and an
   uninstall deleted it (the lead's fetched FFmpeg on this VM sits there). The hook moves the
   program to `%LOCALAPPDATA%\Programs\Reframe` (Windows' per-user programs folder), on the
   directory page (`MUI_CUSTOMFUNCTION_GUIINIT`) and for a silent install (the pre-install hook).
   Checked: the directory page shows the new folder, the files land there, the uninstall entry
   (`HKCU\…\Uninstall\Reframe`, publisher `reframe`) points there.
2. **WebView2**: `webviewInstallMode` `downloadBootstrapper` (Tauri's default, written out): the
   installer reads WebView2's `pv` from the registry and runs the bootstrapper only when the
   runtime is missing. On the VM (WebView2 157) the NSIS install log has no WebView2 line, and the
   MSI log says `INSTALLED_WEBVIEW2_VERSION` 157.0.4341.46, *Skipping action:
   DownloadAndInvokeBootstrapper (condition is false)*. A machine without WebView2 (none here)
   needs the internet during the install; not checked.
3. **MSI** (optional, WiX): **per machine by nature**: it needs an administrator (UAC), installs
   into `C:\Program Files\Reframe` for every user, puts the Start menu shortcut in
   `ProgramData` and a desktop shortcut on the *Public* desktop, and registers the file classes in
   `HKLM`. It has no PATH offer (Tauri's "PATH Environment Variable" feature only holds the main
   binary) and the app never offers updates to an MSI install (an administrator deploys the next
   MSI). For administrators who deploy software; the NSIS installer is the one for users.
   Installed and removed quietly from an elevated shell (`msiexec /i … /qn`, `/x`): nothing left.
4. `notices\THIRD_PARTY_NOTICES` (1 MB, with the updater's crates) is in both installs (L's
   `notices\.gitignore` ships too). **Found in task L's script (not my file)**: on Windows
   `third-party-notices.py` fails reading `cargo about`'s output with the ANSI code page
   (`UnicodeDecodeError` in the reader thread, then `json.loads(None)`); run with
   `PYTHONUTF8=1` it works. Its subprocess calls need `encoding="utf-8"`.

**Signing** (`desktop/packaging/windows/test-certificate.ps1`, the owner's contract): a
self-signed `CN=Reframe test signing` code-signing certificate in `Cert:\CurrentUser\My`
(non-exportable key), its public part in `LocalMachine\Root` and `LocalMachine\TrustedPublisher`
(the machine stores: an import into `CurrentUser\Root` waits for a click), and an overlay
`{"bundle":{"windows":{"certificateThumbprint":…,"digestAlgorithm":"sha256"}}}` that the build
takes as `npx tauri build --config <overlay>` (written outside the repository; the thumbprint is
per machine). `signtool verify /pa`: *Successfully verified* for both installers;
`Get-AuthenticodeSignature`: `Valid` for both, and for the installed `Reframe.exe`,
`uninstall.exe` and `sidecar\reframe-server.exe`. No timestamp server was used, so the
signatures end with the certificate (two years). **SmartScreen**, with a Mark of the Web
(`Zone.Identifier` ZoneId 3) on a copy started from Explorer: unsigned, *Windows protected your
PC*, *Publisher: Unknown publisher*; signed, the same warning with *Publisher: Reframe test
signing*. SmartScreen warns about any installer without download reputation; a self-signed
certificate is trusted only where its root was imported. **A real release needs a certificate
from a certification authority** (an EV or Trusted Signing certificate builds SmartScreen
reputation); the release job then passes its thumbprint, or a `signCommand` for a cloud key, in
the same overlay.

### Install, run, uninstall

Installed version A (0.1.0) by its installer from the console session: Welcome, the folder
page, the PATH question (below), Finish (*Run Reframe*, *Create desktop shortcut*). Started
from the Start menu shortcut (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Reframe.lnk`,
target `…\Programs\Reframe\Reframe.exe`): the sidecar is
`…\Programs\Reframe\sidecar\reframe-server.exe`, the app's child; the first-run screen lists
**ffmpeg and ffprobe (n9.0.2-17), mkvpropedit (103.0) and mediainfo (26.10), each "Bundled with
Reframe"** at `…\Programs\Reframe\tools\…`; *Continue* stored `reframe.firstRun.seen`, and every
later start (also after the update) went straight to the workspace, so WebView2 keeps the flag
(task U's open item). A real encode: `reframe encode vfr.mkv -o …` from a console opened through
Explorer handed its job to the app's sidecar ("Queue: Reframe 0.1.0.dev0 (pid 1316)"), done in
1 s with the bundled FFmpeg.

Uninstalled with the uninstaller's two choices. **What it removes and what it keeps:**

| | Unticked "Delete the application data" | Ticked |
|---|---|---|
| `%LOCALAPPDATA%\Programs\Reframe` (the program), Start menu and desktop shortcuts, the uninstall key, the PATH entry, the file classes `Reframe.<ext>` and the extensions' saved classes | removed | removed |
| `%LOCALAPPDATA%\Reframe` (queue, settings, presets, logs, cache, fetched tools) | kept | removed (the hook) |
| `%LOCALAPPDATA%\org.reframe.desktop` (WebView2's profile, the first-run flag), `%APPDATA%\org.reframe.desktop` (`desktop.json`, window state) | kept | removed (Tauri) |
| `HKCU\Software\reframe\Reframe` (install folder, installer language) | kept | removed (Tauri) |

User data and settings stay unless the user ticks the box; a tick removes everything the app
made. Left in both cases: `%LOCALAPPDATA%\Programs` itself (Windows' folder, empty) and Explorer's
own "Open with" history (`FileExts\.mkv\OpenWithList`), which Windows writes. Checked after
updates too (below).

**Defect found and fixed: an update broke the file associations' restore.** Tauri's
`APP_ASSOCIATE` saves an extension's class as `Reframe.<ext>_backup` and the uninstaller puts it
back; installed over itself (the update) it saved Reframe's own class, so the uninstall left
`HKCU\Software\Classes\.mkv` (and the six others) pointing at the deleted `Reframe.mkv`, plus the
`_backup` values. The pre-install hook now puts the earlier class back before Tauri saves it,
and the post-uninstall hook drops the saved value, an empty class and an extension key that held
nothing else (`.ts` and `.webm` had none before). Checked with C (0.1.2) updated to D (0.1.3)
and uninstalled: every extension key as before the first install.
`testing/tests/test_windows_packaging.py` checks the hook lists every extension and class of
`bundle.fileAssociations`.

### The PATH offer

- The question (*Add the reframe command-line tool to your PATH?* with the folder): **Yes** wrote
  `…\Programs\Reframe\sidecar` at the end of `HKCU\Environment\Path` (REG_EXPAND_SZ, the other
  entries unexpanded); a console opened from Explorer afterwards found it (`where reframe`,
  `reframe version` → 0.1.0.dev0) and encoded. **No** left the PATH unchanged. The uninstall
  removed the entry.
- **An update keeps the entry, and asks nothing.** The updater runs the installer with
  `/P /UPDATE /R`; in update mode Tauri's installer overwrites the folder without running the
  old uninstaller, so the entry stays valid. The question was shown before in passive mode (only
  `/S` skipped it): it now shows only in an interactive, non-update install, and an uninstall that
  is part of an update keeps the entry. Checked: A installed with Yes, updated to B: the entry
  is still there; C installed with No, updated to D: still no entry; no question appeared during
  either update. A newer installer run by hand shows Tauri's "uninstall before installing"
  choice; with it the old uninstaller removes the entry and the new installer asks again (read
  from the template, not run).

### File associations and the Explorer double-click

The installer registers `HKCU\Software\Classes\Reframe.mkv` (and `.mp4`, `.m2ts`/`.ts`, `.avi`,
`.mov`, `.webm`) with `"…\Reframe.exe" "%1"` and makes it the extension's class. Explorer shows
the files with Reframe's icon, the context menu's default verb is **Open with Reframe**, and
**Open with** lists Reframe (with Photos and Windows Media Player). A Windows 10 per-user
`UserChoice` (here Movies & TV for `.mkv`) is not changed by an installer.

**A real double-click** (an Explorer window on the fixtures in the console session, a mouse
double-click by `mouse_event` on the file's row, as a person's): with the app closed, `vfr.mkv`
started `Reframe.exe "C:\Users\TestWin\w-media\vfr.mkv"` (Explorer's child), the file opened,
Reframe's window in the foreground. With the app running, a click on Explorer (Explorer in the
foreground) and a double-click on `vfr.mp4`: the second process handed the path over and exited
(one `Reframe.exe` left), `vfr.mp4` opened in the running window (grouped with `vfr.mkv`), and
Reframe's window came to the front. 0070's open item is closed.

### The notification's identity

The NSIS shortcut carries `System.AppUserModel.ID` = `org.reframe.desktop`, and the notification
plugin uses the bundle identifier when the app does not run from a `target\…` folder. A *Job
done* toast while the window had no focus (a CLI job handed to the installed app): Windows'
notification store (`wpndatabase.db`) has it under the handler `org.reframe.desktop`
(`app:desktop`), and a screenshot shows the toast titled **Reframe** with the app's icon. The
installed app's identity is right; nothing to fix.
The MSI's Start menu shortcut sets the same AUMID (WiX template). Owner: confirm the look by eye.

### Long paths

**The installer does not offer to turn on long paths.** `LongPathsEnabled` is a machine policy
in `HKLM`: the per-user installer has no administrator rights by design and cannot write it, and
asking for elevation for this one value would bring back the UAC prompt the per-user installer
exists to avoid; it also changes every program on the machine. The app already says, wherever a
path is refused, that Windows refuses it and how to turn on long paths
([0070](0070-windows-testing-phase.md) "The Windows-specific risks"). The MSI could write it, but
an application installer that silently changes a system policy is not wanted either. The VM
stayed at `LongPathsEnabled` 0.

### The updater

`tauri-plugin-updater` 2.14.1 (the newest 2.x; without its `zip` feature, which only the v1
archives and macOS need), registered in `main.rs` with a small plugin of `updater.rs`. No
frontend part and no capability: the check, the question and the install run in Rust, the page
is reached only through the quit flow. The smallest UI the plan needs (07 names no UI):

- **When**: once per start, in the background, only in an app an installer made
  (`bundle_type()` NSIS, AppImage or deb). A build run from its folder (`--no-bundle`, the smoke
  tests, development) never asks the network; an rpm install is left out (the plugin would take
  the AppImage path and fail after the user agreed); an MSI install too (above). A failed check
  shows nothing (offline is normal).
- **How the user agrees**: a native dialog *Update Reframe*: "Reframe 0.1.1 is available (this
  is 0.1.0). Reframe downloads it in the background, then quits to install it and starts again.
  If jobs are running, you are asked first." with **Install and restart** · **Later** (Later asks
  again at the next start).
- **Then**: the download (verified against the public key before anything else); then the quit
  flow of D-3 (`request_quit`): with a running or paused job the page asks *Quit Reframe? 1 job
  is running or paused* (Cancel keeps the app and the update waits for the next quit; *Keep
  running in tray* likewise); the install runs as the app exits, after the sidecar has stopped
  (the plugin exits the process when it starts the installer, so the hook stops the backend
  first). A failed download or signature shows *The update could not be installed* with the
  reason. The NSIS installer runs passive and starts the new version (`/R`).
- **Defect found and fixed**: the plugin keeps the installer it ran in
  `%TEMP%\Reframe-<version>-updater-<random>\` (115 MB; it cannot delete itself while it runs).
  The next start removes such folders (checked: C's start removed B's, the second start of D
  removed D's; the first start right after an update finds the installer still running and leaves
  it).

`plugins.updater` in `tauri.conf.json`: the endpoint
`https://github.com/PeterKelemen2/reframe/releases/latest/download/latest.json`, `windows.installMode`
`passive`, `requireSignedVersion` `true` (the signature must carry the version the manifest
announces), and the public key. **The committed `pubkey` is the test key** (minisign key id
`80B98CB268A32743`), generated with `tauri signer generate` on the host into
`~/.config/reframe-test-keys/` (the private key and its password there, mode 600, never on the
VM or in the repository). A real release replaces it with the release key's public part.

**The test** (the host served `latest.json` and the installer on `192.168.122.1:8740`, reachable
from the VM; the test builds took an overlay with that `http://` endpoint and
`dangerousInsecureTransportProtocol`, not committed): the installers were built on the VM,
copied to the host and signed there (`tauri signer sign -f … --app-version 0.1.1`), the
`.sig` went into a static `latest.json` (`platforms."windows-x86_64-nsis"`).

1. A manifest whose signature belongs to another file: A downloaded the installer and showed
   *The update could not be installed. The signature verification failed*; A stayed.
2. A manifest announcing 0.1.2 with 0.1.1's (version-bound) signature: *The update was signed for
   version 0.1.1 but the update endpoint announced version 0.1.2* — refused.
3. The right manifest, with a paused job: **Install and restart** → download → *Quit Reframe? 1
   job is running or paused* → Cancel (A ran on) → closing the window asked again → **Stop jobs
   and quit**: A and its sidecar ended, the passive installer ran for 16 s without a question, and
   B started by itself. After it: the uninstall entry says 0.1.1, the new `Reframe.exe` is signed
   (`Valid`), the PATH entry is still there, `settings.json` is byte-equal (MD5), the first-run
   flag kept (straight to the workspace), the paused job `interrupted` ("Reframe was closed while
   the job was running"). The same with C → D (no job: the app quit at once).

**The release endpoint and the release job** (not built: no workflow runs on GitHub in this
run). The endpoint is GitHub's "latest release" asset URL, so it answers only when the
repository's releases are public (the repository is private today: every check then fails
quietly). The Windows job of a release, after CI's steps:

1. `uv sync --frozen`; `npm ci` in `frontend/` and `desktop/`; `uv run python
   scripts/bundle-tools.py --platform windows-x64`; `uv run python desktop/sidecar/build.py`;
   `PYTHONUTF8=1 uv run --with pip-licenses==5.5.5 python scripts/third-party-notices.py
   --platform windows-x64` (`cargo-about` 0.9.3 installed with `--features cli`).
2. Write the signing overlay with the release certificate (thumbprint, `digestAlgorithm`
   `sha256`, a `timestampUrl`) and run `npx tauri build --config <overlay>` (version from
   `tauri.conf.json`).
3. Sign the updater artefact with the release key from a secret: `tauri signer sign -f <key>
   --app-version <version> Reframe_<version>_x64-setup.exe` (password in
   `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`). Setting `bundle.createUpdaterArtifacts` with
   `TAURI_SIGNING_PRIVATE_KEY` in the build does the same; it stays off in the committed config
   because every build would then need the private key.
4. Write `latest.json`: `version`, `notes`, `pub_date` (RFC 3339) and
   `platforms."windows-x86_64-nsis"` with `signature` (the `.sig` file's content) and `url` (the
   release asset's download URL). No generic `windows-x86_64` key (it would also reach other
   Windows installs) and no MSI entry. Linux entries (`linux-x86_64-appimage`,
   `linux-x86_64-deb`) only after the Linux update is checked (not done).
5. Upload the two installers, the `.sig` and `latest.json` to a GitHub release that is not a
   pre-release.

**Not verified**: the Linux update (AppImage, deb); an update from an MSI install (left out on
purpose); a machine without WebView2; the MSI's UAC prompt (owner, below); a manually run newer
NSIS installer over an older one; the GitHub release path.

**Tests**: `desktop/src-tauri/src/updater.rs` (2: which installs check — mutations: MSI added
to the list, rpm added, deb removed, each failed; the installer folders the
start removes — mutations: no `-` after the name, an empty version accepted, each failed),
`testing/tests/test_windows_packaging.py` (2: every extension and class of
`bundle.fileAssociations` is in the hook — mutation: the `ts` line removed, failed; the per-user
mode and the folder the hook moves away from — mutation: the hook's target set back to
`%LOCALAPPDATA%\Reframe`, failed). The rest is installer behaviour, checked on the VM above.

**For the owner's session** (on the VM, nothing else needed): the UAC prompt of the signed MSI
(`C:\Users\TestWin\w-out\D\msi\Reframe_0.1.3_x64_en-US.msi`, double-click: it should name
*Verified publisher: Reframe test signing*; the prompt is on the secure desktop, so no screenshot
was possible; Cancel, or install and remove it); the toast's look (install
`C:\Users\TestWin\w-out\D\nsis\Reframe_0.1.3_x64-setup.exe`, finish any job while another window
has the focus; the update check of this test build fails quietly since the test server is
stopped).

## Task S — the smoke tests (D-9)

Built on `m10-hardening` 1d8398d (2026-11-12): the Linux run, the CI job and the Windows
preparation; the Windows run on 2907ded (after T2 and W). **On Windows the unchanged app cannot
be driven by msedgedriver** (the app drops msedgedriver's browser arguments); with a five-line
change to `comfort.rs`, which this task does not own, all six steps pass (below).

**The test** (`desktop/tests/smoke/smoke.test.ts`, `processes.ts`, `close-window.py`): Node's own
test runner (`node --test`, TypeScript run by Node 24's type stripping) and `selenium-webdriver`
4.52.0 (the client of Tauri's WebDriver guide), `tauri-driver` 2.1.0 (`cargo install --locked`;
3.0 is an alpha) in front of `WebKitWebDriver` or `msedgedriver`. `npm run smoke` in `desktop/`
starts `tauri-driver` on 8770/8771 with this run's own `REFRAME_DATA_DIR`, `REFRAME_CONFIG_DIR`,
`REFRAME_CACHE_DIR`, `REFRAME_POWER_DRY_RUN=1` and, on Linux, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`,
`XDG_CACHE_HOME`, all in one temp folder that it removes (on Windows msedgedriver gives WebView2
its own profile in `%TEMP%\scoped_dir…`).
The app is `REFRAME_SMOKE_APP`, else the release build in `$CARGO_TARGET_DIR` (or
`src-tauri/target`). Six steps, each skipped once one before it failed; a failed step prints the
sidecar log's last lines and the page's text:

1. **starts**: a WebDriver session with `tauri:options` `{application, args: [<temp>/media/multitrack.mkv]}`
   (no `args` on Windows, see 4), the page's title becomes *Reframe*, and the app runs below
   `tauri-driver`. The session must open within 60 s.
2. **reaches its backend**: the page shows `[data-connection="open"]` (or the backend error
   screen, reported with its text), and the app's own child is `reframe-server` (the frozen
   sidecar; the folder above it is the app's resource folder).
3. **the first-run screen**: shown on the first start, its ffmpeg path is inside the resource
   folder (the bundled build), **Continue** opens the workspace (task U's screen, the way a user
   goes past it).
4. **the file from argv**: a source item with the fixture's exact path, probed (its summary holds
   the probe's `320×180`), and the editor has its job. On Windows the path comes from a second
   launch, `Reframe.exe <fixture>` (open-with), which must hand it over and exit 0: msedgedriver
   cannot pass a path (below).
5. **a job**: the preset picker → *Fast 720p30* (libx264), **Add to queue**, the output path from
   the status bar (next to the file, in the temp folder), **Start**, the status bar's queue link;
   the one row of the queue table reaches `done` (any end state fails at once), and the output
   file exists and is not empty.
6. **the quit**: the app's process tree is listed; the main window gets the close button's
   message (X11 `WM_DELETE_WINDOW` through python-xlib; `WM_CLOSE` on Windows); within 20 s no
   process of that tree, no process whose program is inside the resource folder (the sidecar,
   the bundled FFmpeg), and no process with `--parent-pid <app>` is alive; no `.part` file is in
   the output folder; and `sidecar.log` has `"POST /api/system/shutdown HTTP/1.1" 204` (only the
   quit flow sends it: after a kill the sidecar ends on its parent watch instead).

**Deviations from the plan and the brief**:

- **No short range**: the job editor has no range control yet (`JobSettings.range` exists, no UI
  sets it). The fixture is 4 s at 320×180, so the whole file encodes in about 1 s; the test
  uses the whole file.
- **The quit is the window's close button**, sent by the test, not WebDriver's *Close Window*
  (the page has no `core:window:allow-close` permission, and a close through the webview is not
  the user's path). With no job running the page quits at once (0069).
- A mutation of the app needs the copy in a folder named `target/<profile>/` with a
  `.cargo-lock` file: **Tauri reads the resources beside the binary on Linux only in a Cargo
  output folder** (`tauri-utils` 2.10.2 `resource_dir_from`; else `../lib/<productName>` or
  `/usr/lib/<productName>`), so a copied release binary elsewhere finds no sidecar ("No such file
  or directory (os error 2)" on the error screen). Windows always uses the binary's folder.

**Real tool behaviour found** (checked in the runs below):

- `tauri-driver` 2.1.0 passes `tauri:options.args` to `webkitgtk:browserOptions.args` (Linux)
  and `ms:edgeOptions.args` (Windows) and sets `TAURI_WEBVIEW_AUTOMATION=true` for the native
  driver. On Linux the release build accepts the session with no change to the app.
- **`WebKitWebDriver` waits without end** for an app that exits before its page loads (the
  session request never answered in 10 minutes): the test gives the session 60 s.
- WebDriver's element text is the *visible* text: in the 1280×800 window under Xvfb the sources
  panel's summary and the preset picker's label are cut by the layout, and `getText()` returns
  `""` for them. The test reads `textContent`.
- The queue view fills its table a moment after it opens (zero rows at first).

**Linux run** (2026-11-12, this host, Docker 29.9.2): `desktop/tests/smoke/linux/run.sh` builds
an image from plain `ubuntu:22.04` (task L's pinned digest) with what GitHub's runner and the
job's setup steps bring (build-essential, Git, Python 3, Rust 1.99.1, Node 24.22.1, uv 0.13.5)
and **exactly the job's apt list**, `linux/apt-packages.txt` (the CI step installs the same
file), pipes a clean copy of the working tree into a container and runs `linux/in-container.sh`:
the CI job's steps (`uv sync --frozen`, `bundle-tools.py --platform linux-x64`, the frozen
sidecar, `npm ci`, `npx tauri build --no-bundle`, `cargo install --locked tauri-driver@2.1.0`,
`make-testdata.py --only multitrack` with the bundled FFmpeg, the type check, oxlint and oxfmt of
the test) and `dbus-run-session -- xvfb-run -a -s '-screen 0 1600x1000x24' npm run smoke`.
WebKitWebDriver is Ubuntu 22.04's `webkit2gtk-driver` 2.50.4. Volumes
`reframe-s-{cargo,target,cache}`. The first runs used an image built on task L's `reframe-l`,
which hid that the job's apt line lacked T2's libva build tools (meson, ninja, libdrm's headers:
`bundle-tools.py` stops without them); the lead found it, and the list now has them. The output
(the last full run, on the plain image):

```
▶ the desktop app
  ✔ starts
  ✔ reaches its backend
  ✔ shows the first-run screen with the bundled FFmpeg, and goes past it
  ✔ opens and probes the file given on its command line
  ✔ queues a job and finishes it
  ✔ quits without leaving processes or files behind
✔ the desktop app
ℹ tests 6 · pass 6 · fail 0
```

The steps took 0.5, 0.8, 0.5, 0.9, 2.1 and 0.6 s (the whole test 5.6 s); `bundle-tools.py`
built libva 2.24.1 with the list's meson and ninja; the release build took 1 min 50 s on warm
volumes. The mutations below ran on the earlier `reframe-l`-based image (1d8398d).

**Mutation check** (Linux container; each run against a broken copy of the release app, or of
the test, in `/tmp/m/target/release/`; an unchanged copy passed before and after them, 5 times
in all; two earlier baseline failures were the test's own: the queue table read before it
filled, and an orphan of the previous mutation still running, which the harness now kills
first):

| Mutation | Step that failed | Message |
|----------|------------------|---------|
| the app exits at once (`reframe-desktop` replaced by `exit 1`) | starts (60 s) | the app opened no page within 60 s |
| the sidecar exits at once | reaches its backend | the backend failed: The Reframe server is not running · The server ended before it was ready (exit status: 1) · … |
| no bundled FFmpeg (`tools/ffmpeg/` removed) | the first-run screen | ffmpeg  is not the one bundled in /tmp/m/target/release |
| the app gets a path that does not exist | the file from argv (30 s) | …/multitrack.mkv from the command line is not in the sources |
| the encode fails (`ffmpeg` wrapped: exit 1 for an output `.part`) | a job | the job ended failed |
| an FFmpeg left running (the wrapper starts a detached `ffmpeg` under `setsid`) | the quit | still running 20 s after the quit: 1589 /tmp/m/target/release/tools/ffmpeg/bin/ffmpeg.real |
| a `.part` file left (the wrapper writes `stray.part.mkv`) | the quit | a .part file is left next to the output |
| the app killed (`SIGKILL`) instead of closed | the quit | no shutdown request |

With the kill, the sidecar and the WebKit processes still ended within 20 s (the sidecar's
`PR_SET_PDEATHSIG` and parent watch), so only the log check tells the kill from a quit on Linux.

**The CI job** (`desktop-smoke` in `ci.yml`, `ubuntu-22.04` and `windows-latest`, 60 min): the
steps of `in-container.sh`, the apt packages of `linux/apt-packages.txt` (Tauri's, meson,
ninja-build, pkg-config, gcc, libdrm-dev, webkit2gtk-driver, xvfb, xauth, python3-xlib), and on
Windows
`desktop/tests/smoke/msedgedriver.ps1`: it reads the WebView2 runtime's version (`pv` of the
EdgeUpdate client `{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`, machine or user), downloads
`https://msedgedriver.microsoft.com/<version>/edgedriver_win64.zip`, checks the driver's
Authenticode signature (Microsoft; no checksums are published) and that `--version` names the
same version, and the job puts the folder on `PATH` (where `tauri-driver` looks). The Linux
runner is `ubuntu-22.04`, the oldest supported distro and the image of the Linux run; it must
move when GitHub retires that image. Not run (nothing is pushed): **actionlint was not run**
(its release download was refused by this session's permission rules); the file parses as YAML
(PyYAML 6.0.3) with the job and its 16 steps as written, and every Linux step ran in the
container above. The Windows runner's own steps are not verified: its MediaInfo download may
need `SSL_CERT_FILE` as on the VM (task T), and whether its WebView2 matches an msedgedriver on
the new download host. **The Windows leg fails at "starts" until the app forwards msedgedriver's
browser arguments** (below).

**Windows preparation** (the VM, over SSH, no GUI): `tauri-driver` 2.1.0 installed in
`~/.cargo/bin`; `msedgedriver.ps1` fetched `msedgedriver` **157.0.4341.46** for WebView2
157.0.4341.46 into `C:\Users\TestWin\wt\s-tools\msedgedriver` (signature and version checks
passed); the clone `~/wt/s` built with `bundle-tools.py --platform windows-x64` (with
`SSL_CERT_FILE` from certifi), the frozen sidecar and `npx tauri build --no-bundle` in
`C:\Users\TestWin\cargo-agents`, copied at once to `C:\Users\TestWin\wt\s-app` (`Reframe.exe`,
`sidecar/`, `tools/` with ffmpeg, mkvtoolnix and mediainfo, `notices/`; 336 MB); the fixture
generated with the bundled FFmpeg. The process listing (`Get-CimInstance Win32_Process` through
`-EncodedCommand`, 154 processes in about 1 s) and the path rules work there.

**The Windows run** (2026-11-12, the VM, `m10-hardening` 2907ded with this task's test; the
release build rebuilt there with T2's sidecar and W's updater and copied to `wt\s-app`;
`query user`: `testwin`, console, Active). `npm run smoke` ran in the logged-on console session
from a scheduled task (`schtasks /Create … /IT`, a `.cmd` with msedgedriver 157.0.4341.46 and
`tauri-driver` on `PATH` and `REFRAME_SMOKE_APP`).

1. **The unchanged app: "starts" fails** (twice): `SessionNotCreatedError: session not created:
   DevToolsActivePort file doesn't exist`, the page never reached by the driver although the app
   ran, its sidecar served the page and the page connected (`sidecar.log`). A stand-in program
   started through the same session showed what msedgedriver hands the app: the argument
   `--c:\users\testwin\appdata\local\temp\reframe-smoke-ddykqv\media\multitrack.mkv`, and the
   environment `WEBVIEW2_USER_DATA_FOLDER=%TEMP%\scoped_dir6360_755741909` and
   `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--allow-pre-commit-input … --remote-debugging-port=0
   --test-type=webdriver …`. The app's `msedgewebview2.exe` ran with
   `--user-data-dir=%TEMP%\scoped_dir…\EBWebView` (the folder variable is used) but its switches
   were wry's own (`--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection
   --autoplay-policy=no-user-gesture-required`) and **no `--remote-debugging-port`**: wry 0.57.1
   always sets `AdditionalBrowserArguments` in the environment options
   (`webview2/mod.rs` `create_environment`), and WebView2 157 then ignores the variable. So
   msedgedriver finds no DevTools port.
2. **msedgedriver turns every `args` entry into a switch**: `--` in front, in lower case (Chromium's
   switch parsing on Windows). The app drops `--…` as a flag, so a path cannot be given at the
   first launch through WebDriver; the test gives it through a second launch (open-with, D-5)
   on Windows.
3. **An experiment build** (the VM clone only, not committed): `comfort.rs`'s main window with
   ```rust
   #[cfg(windows)]
   let window = match std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS") {
       Ok(extra) => window.additional_browser_args(&format!(
           "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection {extra}"
       )),
       Err(_) => window,
   };
   ```
   (wry's default switches plus the variable's). With it **all six steps pass**: starts 1.5 s,
   backend 0.8 s, first-run screen 0.1 s (ffmpeg bundled from `wt\s-app\tools`), the file from a
   second launch 0.5 s, the job 1.1 s, the quit 1.6 s; the whole test 6.8 s. W's updater check
   did not get in the way. Windows mutation: the app killed (`process.kill`, `TerminateProcess`)
   instead of closed: the Job Object ended the sidecar and the WebView2 processes within the
   20 s, and the step failed with "no shutdown request" (as on Linux).
4. **For the lead (the app's code, not this task's files)**: the change above, better gated on
   `TAURI_WEBVIEW_AUTOMATION=true` (what `tauri-driver` sets) so that a user's environment never
   changes the webview's switches, and also for the preview window. Without it the CI job's
   Windows leg fails at "starts".
5. Seen on the way: the session opens before the page has loaded (the title is empty at first:
   the test waits for it); after each run msedgedriver's `%TEMP%\scoped_dir…` profile stays (the
   app ends before the session is deleted). The run left the shared
   `%LOCALAPPDATA%\org.reframe.desktop` and `%APPDATA%\org.reframe.desktop` (`.window-state.json`
   of 18:59) unchanged; the five `scoped_dir…` folders of these runs, the scheduled tasks and the
   stand-in program were removed.

## Review and fix round

*Placeholder: filled by the lead.*

**Fix round — FU** (Settings → Tools and the first-run screen; reviewer R2's two minors; this
amends "Task U" items 1 and 3).

1. *A damaged fetched FFmpeg could not be repaired from the web UI.* `ToolInfo.bundled` is
   true as soon as ffmpeg or ffprobe is in a bundled root, and that includes `<data dir>/tools`,
   where *Use bundled FFmpeg* (`POST /api/system/tools/fetch`) installs. A fetched build that
   lost a file hid the section's download and the first-run screen's *Use bundled FFmpeg*. A web
   user then had only *Check again* on the blocking screen, but the server's fetch installs the
   build again over the damaged one (`is_installed` compares the marker's file hashes).
   Now the download is offered again in **web mode** when an FFmpeg tool with origin `bundled`
   is not `found`. Settings paths no longer stop it: the click downloads first, then removes the
   paths, as M4 did. It is **not offered in the desktop app**. There the fetch also installs into
   `<data dir>/tools`, but discovery searches the app's own `<exe dir>/../tools` first, so a
   damaged install folder stays the one that is found. The reason says to reinstall. Limit: a
   web server whose damaged build is in a system root (`/opt/reframe/tools` in the Docker
   image, `/usr/lib/reframe/tools`) also gets the button, and the download into the data folder
   (searched last) does not fix that build. `SystemInfo` does not give the client the data
   folder, so the client cannot tell these cases apart. A file in the read-only image layer is
   damaged only by a user's own change, so the button is accepted there.
2. *The ffmpeg row offered "Use bundled" when ffmpeg already ran the bundled build, and the
   click removed only ffprobe's path.* *Use bundled* now shows on a row only when that row's
   own tool has a Settings path. It still resets the whole family. When the click also removes
   the other FFmpeg tool's path, a note under the row says so: "Use bundled also removes the
   path of ffprobe."

Checked (2026-11-12, this host): unit tests, each failing before the fix (4 of the new ones;
the desktop guard passes before and after). Then the web app (`build:web`) against
`scripts/dev-server.py` (port 8745, then 8747 after the last change) in headless Chromium. The
pinned build was fetched into the server's data folder through the API. Then `bin/ffprobe` was
deleted and the tools were found again. The blocking screen showed "…has no ffprobe: the
installation is damaged…" with *Use bundled FFmpeg* and *Check again*. The click sent only
`POST /api/system/tools/fetch` (`downloaded: true`), ffprobe was back, and the workspace showed.
The same damage found by Settings → Tools *Check again* showed the section's download button,
and it repaired the build the same way. With a working fetched build the section showed no
download and no *Use bundled*. Port 8746, with `{"tools": {"ffprobe": "/usr/bin/ffprobe"}}` and
a fetched build: the ffmpeg row ("Bundled with Reframe") had no *Use bundled* and the ffprobe
row had one. Its click sent one `PUT /api/settings` (`/tools/ffprobe` → `null`) and the rescan,
and ffprobe was then "Bundled with Reframe".

## Consequences

*Filled at the end.*

## Plan changes

*Filled at the end.*
