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

Built and checked 2026-11-12 on the AMD desktop (CachyOS, Docker 29.9.2 with the classic
builder, KWin 6.8 for the virtual session), Tauri CLI 2.12.4.

**The build** (`desktop/packaging/linux/`): `Dockerfile` is `ubuntu:22.04` (pinned by digest)
with Tauri's Linux build packages, Node 24.22.1 and rustup 1.29.3 (both checked by SHA-256),
Rust 1.99.1, uv 0.13.5 with CPython 3.14.8, and `cargo-about` 0.9.3 (only for the notices).
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

The tools layout is one line of `build-in-container.sh` (`fetch-tools.py --build default
--install-dir "$tools/ffmpeg"`); `bundle-tools.py --platform linux-x64` replaces it.

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
  PyInstaller resolves the link). 02 §Bundled FFmpeg and 07 §Tool bundling now say
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
  `[builds.default]` of `tools/<folder>.toml`, or of a `[<folder>]` table in another
  `tools/*.toml`: task T's MKVToolNix and MediaInfo manifest is found in either shape.
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

**Tests**: `testing/tests/test_third_party_notices.py` (17 tests: which distributions are listed;
the real frozen sidecar's archives (skipped without a build); pip-licenses' skipped package;
license-checker's README; cargo-about's own crate and target; each pin shape; a tool without a
pin or a licence; the MediaInfoLib URL for the loaded version; the rendering; the
`bundle.resources` entry) and `testing/tests/test_linux_packaging.py` (4: the template with `%F`
and the recommends of both packages; `remove-app-dirs.sh` on erase and upgrade). Each test
function failed under a mutation of the code it covers (23 mutations) and passed again after.

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

*Placeholder: filled by task S.*

## Review and fix round

*Placeholder: filled by the lead.*

## Consequences

*Filled at the end.*

## Plan changes

*Filled at the end.*
