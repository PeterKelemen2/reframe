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

*Placeholder: filled by task W.*

## Task S — the smoke tests (D-9)

Built on `m10-hardening` 1d8398d (2026-11-12): the Linux run, the CI job and the Windows
preparation. The Windows run waits for the VM's GUI session (below).

**The test** (`desktop/tests/smoke/smoke.test.ts`, `processes.ts`, `close-window.py`): Node's own
test runner (`node --test`, TypeScript run by Node 24's type stripping) and `selenium-webdriver`
4.52.0 (the client of Tauri's WebDriver guide), `tauri-driver` 2.1.0 (`cargo install --locked`;
3.0 is an alpha) in front of `WebKitWebDriver` or `msedgedriver`. `npm run smoke` in `desktop/`
starts `tauri-driver` on 8770/8771 with this run's own `REFRAME_DATA_DIR`, `REFRAME_CONFIG_DIR`,
`REFRAME_CACHE_DIR`, `REFRAME_POWER_DRY_RUN=1` and, on Linux, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`,
`XDG_CACHE_HOME` (on Windows `WEBVIEW2_USER_DATA_FOLDER`), all in one temp folder that it removes.
The app is `REFRAME_SMOKE_APP`, else the release build in `$CARGO_TARGET_DIR` (or
`src-tauri/target`). Six steps, each skipped once one before it failed; a failed step prints the
sidecar log's last lines and the page's text:

1. **starts**: a WebDriver session with `tauri:options` `{application, args: [<temp>/media/multitrack.mkv]}`,
   the page's title is *Reframe*, and the app runs below `tauri-driver`. The session must open
   within 60 s.
2. **reaches its backend**: the page shows `[data-connection="open"]` (or the backend error
   screen, reported with its text), and the app's own child is `reframe-server` (the frozen
   sidecar; the folder above it is the app's resource folder).
3. **the first-run screen**: shown on the first start, its ffmpeg path is inside the resource
   folder (the bundled build), **Continue** opens the workspace (task U's screen, the way a user
   goes past it).
4. **the file from argv**: a source item with the fixture's exact path, probed (its summary holds
   the probe's `320×180`), and the editor has its job.
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
  driver; the release build accepts the session with no change to the app.
- **`WebKitWebDriver` waits without end** for an app that exits before its page loads (the
  session request never answered in 10 minutes): the test gives the session 60 s.
- WebDriver's element text is the *visible* text: in the 1280×800 window under Xvfb the sources
  panel's summary and the preset picker's label are cut by the layout, and `getText()` returns
  `""` for them. The test reads `textContent`.
- The queue view fills its table a moment after it opens (zero rows at first).

**Linux run** (2026-11-12, this host, Docker 29.9.2): `desktop/tests/smoke/linux/run.sh` builds
the image `reframe-s` from task L's `reframe-l` (`REFRAME_BUILD_NAME=reframe-l`) plus
`webkit2gtk-driver` (WebKitGTK 2.50 of Ubuntu 22.04), `xvfb`, `python3-xlib` and `tauri-driver`
2.1.0, pipes a clean copy of the working tree into a container and runs
`linux/in-container.sh`: the CI job's steps (`uv sync --frozen`, `bundle-tools.py --platform
linux-x64`, the frozen sidecar, `npm ci`, `npx tauri build --no-bundle`, `make-testdata.py
--only multitrack` with the bundled FFmpeg, the type check, oxlint and oxfmt of the test) and
`dbus-run-session -- xvfb-run -a -s '-screen 0 1600x1000x24' npm run smoke`. Volumes
`reframe-s-{cargo,target,cache}`. The output (the last full run):

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

The steps took 0.3, 0.9, 0.4, 0.5, 2.2 and 0.6 s (the whole test 5.1 s); the release build
1 min 22 s on warm volumes.

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
steps of `in-container.sh`, plus `cargo install --locked tauri-driver@2.1.0`, Tauri's Linux
packages with `webkit2gtk-driver xvfb python3-xlib`, and on Windows
`desktop/tests/smoke/msedgedriver.ps1`: it reads the WebView2 runtime's version (`pv` of the
EdgeUpdate client `{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`, machine or user), downloads
`https://msedgedriver.microsoft.com/<version>/edgedriver_win64.zip`, checks the driver's
Authenticode signature (Microsoft; no checksums are published) and that `--version` names the
same version, and the job puts the folder on `PATH` (where `tauri-driver` looks). The Linux
runner is `ubuntu-22.04`, the oldest supported distro and the image of the Linux run; it must
move when GitHub retires that image. Not run (nothing is pushed): **actionlint was not run**
(its release download was refused by this session's permission rules); the file parses as YAML
(PyYAML 6.0.3) with the job and its 17 steps as written, and every Linux step ran in the
container above. The Windows runner's own steps are not verified: its MediaInfo download may
need `SSL_CERT_FILE` as on the VM (task T), and whether its WebView2 matches an msedgedriver on
the new download host.

**Windows preparation** (the VM, over SSH, no GUI): `tauri-driver` 2.1.0 installed in
`~/.cargo/bin`; `msedgedriver.ps1` fetched `msedgedriver` **157.0.4341.46** for WebView2
157.0.4341.46 into `C:\Users\TestWin\wt\s-tools\msedgedriver` (signature and version checks
passed); the clone `~/wt/s` built with `bundle-tools.py --platform windows-x64` (with
`SSL_CERT_FILE` from certifi), the frozen sidecar and `npx tauri build --no-bundle` in
`C:\Users\TestWin\cargo-agents`, copied at once to `C:\Users\TestWin\wt\s-app` (`Reframe.exe`,
`sidecar/`, `tools/` with ffmpeg, mkvtoolnix and mediainfo, `notices/`; 336 MB); the fixture
generated with the bundled FFmpeg. The process listing (`Get-CimInstance Win32_Process` through
`-EncodedCommand`, 154 processes in about 1 s) and the path rules work there.

**The Windows run**: *waits for the VM's GUI session (phase 2).*

## Review and fix round

*Placeholder: filled by the lead.*

## Consequences

*Filled at the end.*

## Plan changes

*Filled at the end.*
