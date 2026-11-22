# 0100 — The desktop app with Intel QSV on Linux

- Status: accepted
- Date: 2026-11-19
- Steps: D-8, D-10, D-3, D-4, C-10, F-7

## Context

[0099](0099-intel-qsv-on-linux.md) checked QSV and VAAPI on this laptop through the CLI and in
Docker. The desktop packages were last checked on the AMD desktop
([0072](0072-m10-bundling-packaging-smoke-tests.md) task L, the D-10 install tests). This record
is the same laptop with the Linux desktop packages: the owner clicked, the session built,
watched the processes and drove the app's own sidecar through its API.

| Item | Version |
|------|---------|
| Machine | i5-8250U, Intel UHD 620 (gen 9.5, `8086:5917`), 8 threads, 11 GB; KDE Plasma on Wayland |
| OS | CachyOS, kernel 7.3.3-1-cachyos |
| VA / QSV | intel-media-driver 26.3.5 (iHD), intel-media-sdk 23.2.2 (`libmfxhw64.so.1.35`), libvpl 2.17.0, libva 2.24.1-1.1 |
| GStreamer (host) | gst-plugins-base / good / bad, gst-libav 1.28.8 |
| FFmpeg | the pinned `default` build n9.0.2-17-g2a571b6068-20260930 |
| Build | `desktop/packaging/linux/build.sh` (Docker 29.9.3, classic builder), version stamped 0.1.0 and restored |
| Branch | `desktop-qsv-linux` from `m10-hardening` at `7d596d84` |

## Results

**Tooling and build.** Docker with the `docker` group, 57 GB free, `/dev/fuse` with fuse2
2.9.9 and fuse3 3.18.3: nothing missing. The first build took 14 min 38 s (Rust from scratch,
the uv/npm cache volume warm), the next ones 5 min 41 s and 5 min 17 s. AppImage 117 MiB, .deb
and .rpm 43.6 MiB; no `ffmpeg` or `ffprobe` inside, only `usr/lib/Reframe/tools/libva/`
(`libva.so.2`, `libva-drm.so.2`); the newest glibc symbol is `GLIBC_2.35`.

**1. The data folder and the FFmpeg.** The sidecar and the shell both take `REFRAME_DATA_DIR`,
else platformdirs' `~/.local/share/reframe`. `ToolService._libva()` finds `<root>/libva` in the
first bundled tool root next to the frozen sidecar, and a download or *Install from file*
copies `libva.so.2` and `libva-drm.so.2` into the build's `lib/` (the marker records their
hashes).

- a. Fresh data folder (`REFRAME_DATA_DIR` / `_CONFIG_DIR` / `_CACHE_DIR` under
  `~/rf-desktop-test/a/`): the first run lists `default` (9.0.2, recommended) and `compat`
  (8.1.3) with licence, source links, *Download* and *Install from file*; the download
  installed and copied the packaged libva (same SHA-256 as the AppImage's). Every QSV/VAAPI
  ffmpeg the app started mapped (`/proc/<pid>/maps`) the build's own `lib/libva.so.2` and
  `libva-drm.so.2`, `/usr/lib/dri/iHD_drv_video.so` (26.3.5), `libigdgmm.so.12.10.0` and, for
  QSV, `/usr/lib/libmfxhw64.so.1.35`, with `LIBVA_DRIVERS_PATH=/usr/lib64/dri:/usr/lib/dri` and
  no `LD_LIBRARY_PATH` or `APPDIR` from the AppImage. The Media SDK runtime also loads the
  system's `libva-x11.so.2` (2.24.0), which binds to the already loaded packaged `libva.so.2`:
  harmless while both are 2.24. Before the download, discovery used Arch's `/usr/bin/ffmpeg`
  from `PATH`.
- b. The build the CLI fetched (`~/.local/share/reframe`, no packaged libva): the app takes it
  as the `default` build, not outdated, and does not change it; its ffmpeg loads the system
  `libva.so.2.2400.0` with the same iHD and Media SDK runtime.

So QSV and VAAPI work with the packaged libva (built on Ubuntu 22.04) and with the system's,
on iHD 26.3.5 and Media SDK 23.2.2.

**2. Encoders** (Settings → Encoders, the picker, `GET /api/system/encoders`, both builds):
`h264_qsv` available (8-bit), `hevc_qsv` available (10-bit), `av1_qsv` "This Intel GPU cannot
encode AV1"; `h264_vaapi` and `hevc_vaapi` available on `/dev/dri/renderD128`, `av1_vaapi`
"The VAAPI driver has no AV1 encoder"; NVENC "NVIDIA driver not found", AMF "AMD AMF runtime not
found (libamfrt64.so.1)". The same as 0099's CLI list.

**3. Encodes** through the app's queue (`testdata/media`): `h265-qsv-1080p` on `multitrack.mkv`
(HEVC Main, 100 frames, every audio and subtitle track); `h264_qsv` (H.264 High); `hevc_qsv`
10-bit on `hdr10.mkv` (Main 10, `yuv420p10le`, PQ / BT.2020 / bt2020nc, mastering display and
content light level kept); `hevc_vaapi` 8-bit and 10-bit (HDR10 kept). A 3-minute 1080p25
source: `h265-qsv-1080p` in 30 s (4500 frames, about 150 fps). A cancel 8 s into a QSV job: the
ffmpeg was gone within 1.5 s, the `.part` file removed, the job `cancelled`. The preview clip
(`hevc_qsv` 10-bit) and its frames work; playing it in the window crashed the AppImage
(defect 1); the frame compare was a frame off (defect 3).

**4. The desktop parts.** The job notification ("Job done" with the file name, `Notify` from
`reframe-desktop`) and *Show in folder* (Dolphin at the output's folder) work. Taskbar progress:
the app sent 80 `com.canonical.Unity.LauncherEntry.Update` signals for
`application://Reframe.desktop` (progress 0 → 1, then hidden), but Plasma showed no bar for a
plain AppImage run: no `Reframe.desktop` is installed. With a `Reframe.desktop` in
`~/.local/share/applications` (`StartupWMClass=reframe-desktop`) the bar shows. Quit while a
QSV job runs: *Stop jobs and quit*; ffmpeg, the sidecar, the app and the `.part` file were gone
within one 0.5 s sample, the AppImage mount 1 s later; the job is saved `interrupted`. SIGTERM
to the app and the owner's forced quit after the freeze also left nothing. The dialog came
after a few seconds and the UI lagged during the encode: the "hardware" encode uses about 3.3 of
the 8 threads (H.264 decoding, lanczos scaling and the format conversion on the CPU;
`cpu=334%`), and FFmpeg runs at normal priority.

**5. The .deb** in `ubuntu:22.04` (the build image's digest) with `--device /dev/dri`, Ubuntu's
intel-media-va-driver-non-free 22.3.1, libmfx1 22.3.0 and libva 2.14 (too old for the BtbN
build alone): installed with apt; the frozen sidecar in desktop mode downloaded `default`
through `POST /api/system/tools/fetch` and copied the packaged libva; `h264_qsv` (8-bit),
`hevc_qsv` (10-bit), `h264_vaapi`, `hevc_vaapi` available, the AV1 ones with the same reasons;
`h265-qsv-1080p` encoded `multitrack.mkv`; `LD_DEBUG=libs` shows the packaged `libva.so.2` and
`libva-drm.so.2`, Ubuntu's iHD and `libmfxhw64.so.1.35`. CachyOS cannot install a .deb, so the
.deb was not run on this host's driver stack.

## Defects found and fixed

1. **The AppImage's window froze on a preview clip** (`fix(D-8)`). The AppImage carries
   GStreamer 1.20.3 core libraries and no plugins, and linuxdeploy's AppRun sets
   `GST_PLUGIN_SYSTEM_PATH_1_0=$APPDIR/usr/lib/gstreamer-1.0:`, a folder that does not exist.
   The `<video>` made WebKitGTK look for `appsink`, `appsrc` and `autoaudiosink`, print
   `g_signal_connect_data: assertion 'G_TYPE_CHECK_INSTANCE (instance)' failed`, and abort
   WebKitWebProcess (SIGABRT in `libwebkit2gtk-4.1.so.0`, coredump); Tauri does not restart it.
   [0067](0067-m8-picture.md) item 4 lets the `<video>` decide and expects an error event,
   which never came. The shell's `webview_plays_video` command is `false` when GStreamer's
   system plugin path is set and its folders (and the extra plugin path) lack `libgstapp.so`
   and `libgstautodetect.so`; `Platform.canPlayVideo()` asks it (web: `true`), and the preview
   then makes no `<video>`: "this window has no video player", the frame compare and *Open in
   external player* at once. Checked on the rebuilt AppImage.
2. **`REFRAME_FFMPEG_BUILD` reached the desktop sidecar** (`fix(D-3)`). `ad59c574` added it to
   the core's `SERVER_OPTIONS` but not to the shell's copy, so the sidecar would download that
   build at start; `cargo test` failed on m10-hardening
   (`the_server_options_kept_from_the_sidecar_are_the_cores`).
3. **The frame compare was a frame off on 2 of 5 frames** (`fix(C-10)`), on QSV and libx265
   alike. The strip's times are not on the frame grid; `-ss 0.1` keeps the frame at 0.12, the
   clip gives it 0.02, and the encoder rounds that to its 1/25 s time base, so the clip starts
   at 0.04 (an on-grid `-ss 0.12` starts at 0). Measured by PSNR against the neighbouring
   source frames (about 33.5 dB on the match, about 20 dB on its neighbours): the frames at
   t = 0.57 and 1.33 s showed the next source frame. `make_clip` now cuts at the first video
   frame at or after the asked start (`ffprobe -read_intervals`, which takes timestamps, so the
   file's `start_time` is added; `-ss` counts from it) and reports it as `PreviewClip.start`.
4. ***Open in external player* opened Firefox** (`fix(D-4)`): the shell opened the clip's http
   URL, which `xdg-open` gives to the browser. `GET /api/preview/clips/{clip_id}/file` gives the
   cached clip's path in desktop mode only (web: `404 preview.no_clip_file`); `open_external`,
   still only for a clip link of the local server, opens that file (Haruna opened it) and falls
   back to the URL.
5. **The preview window jumped while an output frame rendered** (`fix(F-7)`): the output,
   split and side views showed a one-line "Rendering…" in the picture's place. The waiting box
   now has the last output frame's size (the source frame's before the first one).

Tests: vitest (preview clip without a player, both platform adapters, the waiting box), Rust
(`media` rules, clip id and the server's answer, the existing contract test), pytest (a clip
asked between two frames, lossless, is the job's output frame at `start + t` pixel for pixel;
the clip file route in desktop and web mode). Each new test failed before its fix.

## Decision

1. In-app playback in a webview without its media framework is not tried: the shell answers
   `webview_plays_video`, and the frame compare and the external player stand in. 0067 item 4
   (the `<video>` decides) holds wherever the webview can report an error.
2. The desktop app opens the cached clip file in the user's player; the web app opens the
   signed link.
3. A preview clip starts on a source frame, and `PreviewClip.start` is that frame's time.
4. Not done here: bundling GStreamer plugins into the AppImage (real playback there; size,
   LGPL notices and the source manifest of the AppImage's packages change: the owner's
   decision), installing a desktop entry from the AppImage (taskbar progress), restarting a
   crashed web process, a lower FFmpeg priority.

## Consequences

- The AppImage plays no preview clip in its window, on any host; the .deb and .rpm use the
  distro's WebKitGTK and GStreamer (not checked on a desktop here). A desktop without
  gst-plugins-good would hit the same abort with the .deb; the rule covers only a set plugin
  path.
- `PreviewClip.start` can be later than the asked start by up to one frame; the clip summary
  shows it.
- Taskbar progress in an AppImage needs an installed `Reframe.desktop` (an AppImage integration
  tool or the user); the .deb and .rpm install one.
- Not checked: the .deb and .rpm on this host's driver stack, Tiger Lake and newer, the 60 s
  exit limit, the Windows side of `open_external` with a file (`tauri-plugin-opener`'s
  `open_path`).

## Plan changes

- `07-desktop-app.md`: §In-app video playback (playback decides, as 0067; a webview without its
  media framework; the desktop app opens the clip file); §Native integrations (open
  externally); §D-10 (the laptop result); §Risks (the AppImage's GStreamer).
