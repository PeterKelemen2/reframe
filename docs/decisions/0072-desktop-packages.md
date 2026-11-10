# 0072 — Desktop packages: per-user NSIS in Programs, Linux packages built on Ubuntu 22.04, the updater

- Status: accepted
- Date: 2026-11-10
- Steps: D-8, D-9

## Context

07 D-8: a per-user NSIS installer without admin rights, with the WebView2 bootstrapper and an
optional MSI; code signing recommended; an AppImage built on the oldest supported distro, a
.deb and an .rpm; the updater with a signed `latest.json` in GitHub Releases. D-9: tauri-driver
smoke tests on Linux and Windows. Open question 6 in 01-scope (which artefacts) has no answer,
so its default holds: all of them.

The owner chose on 2026-11-10: **unsigned installers for now**; **the updater key generated
here**, the private key outside the repository; **no long-path offer** in the installer (it
needs admin rights, and the NSIS installer is per-user).

## What was found

1. **Tauri's per-user NSIS default is `%LOCALAPPDATA%\<productName>`**, which is
   `%LOCALAPPDATA%\Reframe`: Reframe's own data folder on Windows (queue, logs, cache, and the
   build of `reframe tools fetch` in `tools\ffmpeg`). Installed on the Windows VM, the app's
   `tools\ffmpeg` and the fetched build were one folder (340 MB with the archive's headers and
   docs), and `queue.sqlite3` sat next to `Reframe.exe`. The uninstaller removes only its own
   files, so no data was lost, but the folders must not be shared. Tauri's template sets the
   default in `.onInit`, where no installer hook runs.
2. **linuxdeploy (AppImage) does not follow the bundled FFmpeg's `RPATH`** (`$ORIGIN/../lib`):
   `ERROR: Could not find dependency: libavcodec.so.63`, then the same for `libva.so.2`.
   `LINUXDEPLOY_EXCLUDED_LIBRARIES` (a `;`-list of globs) makes it leave them alone; it rewrites
   the binaries' `RPATH` to the `RUNPATH` `$ORIGIN/../lib:$ORIGIN`, which still finds them.
3. Tauri's default desktop entry has no `%F`, so a file opened from the file manager was not
   passed to the app (0069).

## Decision

1. **NSIS**: `installMode: currentUser`; Tauri's template of tauri-cli 2.12.4 is shipped as
   `desktop/src-tauri/windows/installer.nsi` with one change, the default folder
   `%LOCALAPPDATA%\Programs\Reframe` (the Windows convention for per-user programs). On a Tauri
   upgrade, take the new template and make the same change. WebView2: the download
   bootstrapper. The MSI is built too (per machine, as WiX makes it).
2. **Unsigned.** SmartScreen warns about the installers: a known limit until there is a
   certificate (`bundle.windows.certificateThumbprint` or `signCommand`).
3. **Linux packages are built in `ubuntu:22.04`** (`desktop/packaging/linux.Dockerfile`,
   `scripts/build-linux-packages.sh`): the frontend, the frozen sidecar, the bundled tools with
   the libva built there, then `tauri build`. Rust 1.99.1, Node 24.22.1, Python 3.14.8 and uv
   0.13.5 are pinned in the image. The packages go to `dist/linux/`. The .deb and .rpm install to
   `/usr/lib/Reframe/` (Tauri's layout, not 02's `/usr/lib/reframe/`): the tools are one
   folder above the sidecar, where discovery looks, so no second path is needed.
4. **Desktop entry**: `desktop/src-tauri/linux/reframe.desktop`, Tauri's template plus `%F`.
5. **Updater**: `tauri-plugin-updater`; the public key is in `tauri.conf.json`, the endpoint is
   `https://github.com/PeterKelemen2/reframe/releases/latest/download/latest.json`. The private
   key and its password are in `~/.tauri/reframe-updater.key` and `.key.password` (mode 600) on
   the build machine; the Linux build mounts them read-only and signs the AppImage, .deb and
   .rpm. The Windows installers are signed with `tauri signer sign` on that machine, so the key
   does not go to the Windows build host. The app checks once, 10 s after the start, and asks
   before it installs ("Install and restart" / "Later"). `REFRAME_NO_UPDATE_CHECK=1` turns the
   check off (smoke tests), `REFRAME_UPDATE_URL` replaces the endpoint (a test release). No
   setting in the UI yet.
6. **Smoke test** (D-9): `desktop/smoke/smoke.py`, a WebDriver client in the standard library,
   run through tauri-driver: the app starts with a fixture in its arguments in a new home, the
   backend answers, the file opens, a job is queued with the default preset and finishes, the
   window closes, and no process of the run is left. `scripts/smoke-linux.sh` runs it in
   `ubuntu:22.04` against the .deb (WebKitWebDriver, Xvfb, tauri-driver 2.1.0).

## Results

- **Linux** (`scripts/build-linux-packages.sh` on this laptop, about 10 minutes from a warm
  cache): `Reframe_0.1.0_amd64.deb` and `Reframe-0.1.0-1.x86_64.rpm` (147 MB each),
  `Reframe_0.1.0_amd64.AppImage` (214 MB), each with its updater `.sig`. The .deb holds
  `/usr/lib/Reframe/{sidecar,tools}` with the shipped libva, `/usr/bin/reframe-desktop`, and the
  desktop entry with `Exec=reframe-desktop %F` and the six MIME types.
- **D-9 on Linux**: `scripts/smoke-linux.sh` passes against the .deb installed in
  `ubuntu:22.04`: the app started, the backend answered, `chapters.mkv` opened from the
  arguments, a job with the default preset finished (`chapters (1).mkv`), and after the window
  closed no process with the run's data folder was left (the first runs found only
  tauri-driver and WebKitWebDriver, which carry it too; they are now left out). WebKitWebDriver
  answers with the legacy element key `ELEMENT`, which the client accepts.
- **Windows VM**: `Reframe_0.1.0_x64-setup.exe` (105 MB) and `Reframe_0.1.0_x64_en-US.msi`
  (132 MB). The silent per-user install takes 29 s, needs no admin rights, and puts Reframe
  in `%LOCALAPPDATA%\Programs\Reframe` (293 MB) with an uninstall entry under HKCU only, the
  Start-menu shortcut and the `.mkv`/`.mp4` associations; the installed CLI finds the bundled
  FFmpeg and mkvpropedit. A machine that had the old location keeps it (the template restores
  the previous install folder from `HKCU\Software\reframe\Reframe`). The silent uninstall
  removes the program and keeps the data.

## Consequences

- The NSIS template is a copy: a Tauri upgrade must bring its changes over.
- The private updater key exists only on this machine: the owner backs it up. Losing it means
  the installed apps cannot take updates signed with a new key.
- The Linux build needs Docker and about 10 minutes from a warm cache.

## Plan changes

- `docs/plan/07-desktop-app.md` D-8, D-9: what is done and how.
- `docs/plan/02-architecture.md` §Bundled FFmpeg: the .deb/.rpm folder.
