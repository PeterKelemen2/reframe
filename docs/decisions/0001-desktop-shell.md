# 0001 — Desktop shell: Tauri 2 with a PyInstaller onedir sidecar (the D-0 result, Linux)

- Status: accepted
- Date: 2026-10-28
- Steps: D-0, S-0

## Context

[07](../plan/07-desktop-app.md) builds the desktop app as a Tauri 2 shell that starts
`reframe-server` as a sidecar, frozen with PyInstaller as a onedir build. D-0
([07 §D-0](../plan/07-desktop-app.md#d-0-spike-do-this-before-the-frontend-is-far-along)) is the
spike that checks this choice before the frontend is far along. On Linux, it must show:

- a minimal app with the onedir sidecar;
- a cold start under 2 s;
- that nothing is left after `kill -9` of the app;
- that drag-and-drop paths, PrimeVue and a canvas magnifier work on WebKitGTK;
- which hidden imports PyInstaller needs.

The Windows items wait for the Windows testing phase of M10
([0053](0053-linux-first-windows-testing-phase.md)).

The spike lives in `desktop/spike/` ([0054](0054-d0-spike-layout-and-parent-watch.md)). It
was built in three tasks:

- 4a: the shell, the sidecar, `--parent-pid`, cold start and cleanup;
- 4b-i: drag-and-drop, PrimeVue, and the window and pointer tools;
- 4b-ii: the magnifier.

How to repeat each measurement: `desktop/spike/README.md` and `desktop/spike/MAGNIFIER.md`.
The raw results are in `desktop/spike/results/`.

There are two machines:

- **The laptop** (4a, 2026-10-23): Intel UHD 620, 8 threads, NVMe SSD, KDE Plasma on Wayland,
  WebKitGTK 2.54.1. Its load was not recorded. The laptop is packed: nothing of 4b was
  measured on it.
- **The AMD desktop** (4b-i, 4b-ii and the lead's repeats, 2026-10-27): Ryzen 5 5600,
  12 threads, Radeon RX 7600, KDE Plasma 6.8.1 on Wayland, WebKitGTK 2.54.2.
  - A movie played on `DP-1` (165 Hz) during every run, and the 1-minute load average was
    1.3 to 4.4.
  - Every window was on `HDMI-A-1` (1920×1080, 60 Hz) and was read back there.

## Decision

**Tauri 2 with a PyInstaller onedir sidecar is confirmed for Linux.** Every Linux item of
D-0 passed:

- the cold start is well under the target;
- the cleanup leaves nothing;
- WebKitGTK gives exact drop paths and renders PrimeVue like Firefox.
- WebKitGTK draws the magnifier at 60 frames per second. With the real pointer and the default
  renderer, the picture follows the pointer at about 54–55 updates per second, because that is
  the rate at which the pointer events reach the page. This does not change the choice; D-1 and
  F-7 take it up (Consequences).

The parts of the result that later steps build on:

1. **The shell** (Tauri 2.12.5, no `tauri-plugin-shell`) starts the sidecar with
   `std::process`:
   - on its main thread, before the window;
   - with `--mode desktop --port 0 --auth token --parent-pid <pid>` and a token made in Rust in
     `REFRAME_TOKEN`;
   - with `PR_SET_PDEATHSIG = SIGTERM` in `pre_exec`.

   The death signal follows the thread that forked, so D-3 must fork on a thread that lives as
   long as the app (`testdata/README.md`, "D-0 (4a)"). SIGTERM, not SIGKILL: uvicorn stops on
   it as on `POST /api/system/shutdown`, so the jobs end `interrupted` and their `.part` files
   are removed.
2. **The parent watch is the second line** (S-0 `--parent-pid`, 0054 "Follow-up (4a)" and
   "Follow-up (review)"):
   - on Linux a pidfd, and the pid counts as the parent only if it is a live ancestor of the
     server or started at least one clock tick before it;
   - on Windows `OpenProcess` plus the creation time;
   - a stop like the shutdown request, then `os._exit(70)` after 5 s;
   - exit 1 when the parent is already gone at start-up.
3. **The onedir build** needs the options in the table below. D-2 takes them over.
4. **Drag-and-drop uses Tauri's drag-drop event.** WebKitGTK's DOM `drop` gives no files.
5. **The magnifier is a canvas**, redrawn once per `requestAnimationFrame` from the last
   pointer position. No tile or worker scheme is needed.

### Cold start (target < 2 s)

10 runs per case, median / worst, in seconds:

- *Sidecar*: from the spawn to the ready line.
- *App*: from the spawn of the app to the page that shows `GET /api/health`.
- *Evicted*: the onedir's pages (and the app binary's, for the app) are dropped with
  `posix_fadvise(POSIX_FADV_DONTNEED)` before each run, and `fincore` shows 0 bytes cached.
  This does not drop the system libraries (GTK, WebKitGTK, glibc). So a first start after a
  reboot is not covered.

| Case | Laptop (4a) | AMD desktop (lead, movie playing) |
|------|-------------|-----------------------------------|
| sidecar, warm | 1.176 / 1.212 | 0.742 / 0.769 |
| sidecar, evicted | 1.393 / 1.445 | 0.838 / 0.843 |
| app, warm | 1.338 / 1.372 | 0.798 / 0.820 |
| app, evicted | 1.469 / 1.526 | 0.895 / 0.936 |
| app, sidecar started in the setup hook, warm / evicted | 1.441 / 1.491, 1.597 / 1.662 | not run |
| `uv run reframe-server` instead of the onedir: sidecar warm / evicted, app warm | 1.167 / 1.261, 1.492 / 1.563, 1.302 / 1.342 | not run |

- On the laptop, the lead's repeat after the merge gave sidecar 1.26 / 1.32 (warm) and
  1.47 / 1.52 (evicted), app 1.40 / 1.44 and 1.54 / 1.60.
- On the AMD desktop, the app runs went through the placement wrapper (`windows run`). Each of
  the 21 windows (11 warm, with the warm-up run; 10 evicted) was read back at 40,40, 900×708 on
  `HDMI-A-1`.
- The AMD runs came before the review's fixes. Then the app used the owner's `~/.cache`, which
  holds a warm WebKitGTK shader cache. Now each app case has its own XDG folders and one start
  that is not counted (`desktop/spike/README.md`, "Isolation"). The numbers were not measured
  again under the new set-up.
- The raw output of the AMD runs is in `results/cold-start-amd-desktop-2026-10-27-*` and
  `results/cleanup-amd-desktop-2026-10-27-*`. F2 recomputed every AMD figure of the cold-start
  and cleanup tables from these files and got the same numbers. The laptop runs kept no raw
  output, so their figures cannot be recomputed. The scripts now write a raw file by default,
  with `/proc/loadavg` before and after each case.
- Where the time goes (laptop, unfrozen, `-X importtime`): 1.04 s of imports. Of these,
  `reframe` takes 372 ms (mostly building pydantic models), `reframe_server` 181 ms and
  `fastapi` 104 ms.
- Starting the sidecar before the window saves about 0.1 s against the setup hook.
- If the target is ever missed: defer guessit, the analysis and the batch modules, and the
  rarely used pydantic models (`defer_build`).

### Cleanup

An x265 (`slow`) encode of `hdr10-4k.mkv` ran through the sidecar's API in each case. "Gone
after" is the time from the kill or the quit until no process of the app, the sidecar or the
encode is left (a zombie counts as gone).

| Case | Laptop (4a) | AMD desktop (lead) | Job, `.part` |
|------|------------:|-------------------:|--------------|
| `kill -9` of the app (death signal and watch) | 0.256 s | 0.241 s | `interrupted`, removed before the server ended |
| `kill -9` of the app, the watch alone | 0.574 s | not run | as above |
| `kill -9` of the app, the death signal alone | 0.181 s | not run | as above |
| `kill -9` of the app, neither | the sidecar ran on as an orphan and finished the encode | not run | `done` |
| `kill -9` of the sidecar alone | at once (FFmpeg has the core's SIGKILL death signal) | at once | `running` in the store, `interrupted` at the next start; `.part` removed then |
| quit (as a closed window: `POST /api/system/shutdown`, then wait up to 5 s) | 0.568 s, 204, not killed | 0.415 s, 204, not killed | `interrupted`, removed |

- After `kill -9` of the sidecar, the app stays open. Its page shows
  `The server ended (signal: 9 (SIGKILL)). Log: …` after 10 ms (laptop) or 8 ms (AMD), and the
  shell does not restart it (D-3 decides about restarts).
- On the AMD desktop, the killed sidecar's FFmpeg was a zombie under `systemd --user` until
  it was reaped.
- The error page (laptop) shows each failure, and the app stays open:
  - a missing binary, after 0.44 s;
  - a sidecar that exits at once, after 0.41 s;
  - a sidecar that never prints the ready line, after 20.07 s (it is then killed).
- A real window close (XWayland, `xdotool windowquit`) takes the quit path: 204, stopped in
  0.63 s, exit 0.

### PyInstaller (6.22.3, hooks-contrib 2026.9)

Each option, and what goes wrong without it (the full table: README "The onedir build"):

| Option | Without it |
|--------|-----------|
| `--collect-data babelfish`, `--collect-submodules babelfish` | crash at start-up (`iso-3166-1.txt`; `babelfish.converters.alpha2`) |
| `--collect-data reframe.presets` | `Application startup failed`, exit 3 |
| `--collect-data language_data` | `GET /api/languages` 500 |
| `--collect-data reframe.definitions` | **silent**: 0 video encoders, `POST /api/jobs/draft` 500 |
| `--collect-data reframe.tools` | the FFmpeg fetch task fails (no `ffmpeg.toml`) |
| `--collect-data guessit` | **silent**: every name parses to its whole stem |
| `--hidden-import pymediainfo`, `--add-binary …/libmediainfo.so.0:pymediainfo` | **silent**: probes run without MediaInfo |
| `--exclude-module mypy`, `--exclude-module hypothesis` | 7 MB more (pydantic's hook pulls them in) |

- No option was needed for pydantic, uvicorn's loops and protocols (the WebSocket works
  frozen), langcodes, websockets, platformdirs or psutil: the contrib hooks cover them.
- The build is 82.5 MB in 1014 files.
- The three silent failures are why D-2 needs a smoke test of the frozen build
  (`tests/test_frozen_sidecar.py` and `scripts/smoke_sidecar.py` are the start).

### WebKitGTK

**Drag-and-drop from Dolphin** (26.08.2), with the real pointer on native Wayland and on
XWayland, and the same results on both (README "Drag-and-drop paths",
`results/drop-*.json`):

- Tauri's drag-drop event gives every UTF-8 path byte for byte:
  - spaces, `Ünnepi film – 2.mkv` and `日本語.mkv`;
  - three files, in Dolphin's order;
  - a folder.

  The page gets the same strings.
- A name that is not UTF-8 (`bad\xffname.mkv`) arrives as `bad\u{FFFD}name.mkv`, which does
  not exist: Dolphin itself sends `%EF%BF%BD`. D-5 can only say that the name cannot be read,
  and offer the file dialog.
- WebKitGTK's own DOM `drop` gives no files and no URI list, only one HTML link to the first
  item. HTML5 drop is not enough on Linux.
- The lead's repeat on the AMD desktop (Wayland, Tauri's handler, the accents and the
  not-UTF-8 cases) gave the same bytes: 79 pointer moves, each read back at its target.

**PrimeVue 4.5.5** with the frontend's preset: DataTable (200 rows), Dialog, Select, Slider,
Tabs and Toast, light and dark (README "PrimeVue 4 rendering", `results/prime/`):

- WebKitGTK and Firefox lay the page out the same to about 1 px.
- Chromium's tab bar is 3 px lower (48 px against 51 px). PrimeVue's `Tab` is a `<button>`
  with the browser's button font (WebKitGTK `600 13px Noto Sans`, Chromium
  `600 13.3333px Arial`). `font: inherit` on buttons in the frontend removes the difference.
- Headed Chromium draws classic 15 px scrollbars; WebKitGTK and Firefox use overlay
  scrollbars.
- No CSP violation from PrimeVue; the page's `eval` test is refused in all three engines.
- The lead's repeat gave the same tab heights and fonts.

**Canvas magnifier** (`MAGNIFIER.md`, `results/magnifier-*.json`):

- **The page**:
  - the real 3840×2160 frame of `hdr10-4k.mkv` from `POST /api/preview/frames`: a signed PNG
    URL, `rgb24` with a `cICP` chunk, decoded with `createImageBitmap`;
  - the fitted frame with a crop, a loupe and four edge strips at 4×
    (`imageSmoothingEnabled = false`), all redrawn on each frame with a new pointer position.
- **The pointer**: an ellipse at about 870 px/s.
  - The real pointer: `/dev/uinput`, a move every 8 ms, each move read back by KWin.
  - Synthetic events: Playwright's `mouse.move` in the browsers, a page-driven `pointermove`
    loop in WebKitGTK.
  - Not measured: input latency, the compositor's presentation, GPU time, real mouse
    hardware, HiDPI and full-screen sizes, crop-line drags.

Real pointer, full redraw, 3 runs of 4 s each:

- Interval and redraw are median / p95 / worst in ms.
- fps is the frame count divided by the sum of the intervals.
- Redraws/s is how often the page drew a new position: a frame redraws only when a pointer
  event came since the last one.
- A frame is dropped when its interval is over 25 ms (1.5 periods at 60 Hz).
- The first interval of each run is left out. It starts at the frame callback that the run
  asked for, which some engines answer at once (`MAGNIFIER.md`, "Numbers").

| Engine | Interval | fps | Redraws/s | Redraw | Dropped |
|--------|----------|----:|----------:|--------|---------|
| WebKitGTK (4b-ii) | 16 / 17 / 19 | 62.2 | 54.37 | 0 / 1 / 1 | 0 of 741 |
| WebKitGTK (4b-ii, repeat) | 16 / 17 / 19 | 62.16 | 54.5 | 0 / 1 / 2 | 0 of 741 |
| WebKitGTK (lead's repeat) | 16 / 17 / 18 | 62.21 | 55.05 | 0 / 0 / 1 | 0 of 741 |
| WebKitGTK, `WEBKIT_DISABLE_DMABUF_RENDERER=1` (4b-ii) | 16 / 18 / 24 | 60.85 | 60.19 | 4 / 5 / 7 | 0 of 729 |
| the same (4b-ii, repeat) | 16 / 19 / 23 | 60.5 | 60.25 | 4 / 5 / 7 | 0 of 724 |
| the same (lead's repeat) | 16 / 17 / 19 | 61.38 | 60.14 | 4 / 5 / 8 | 0 of 735 |
| Chromium 156, headed | 16.7 / 16.8 / 17.1 | 60 | 59.92 | 0 / 0.1 / 0.2 | 0 of 717 |
| Firefox 157, headed | 17 / 17 / 34 | 59.41 | 59.41 | 0 / 1 / 1 | 7 of 712 |
| Firefox 157, headed, repeat | 17 / 17 / 34 | 59.83 | 59.83 | 0 / 1 / 1 | 2 of 717 |

- **The frame loop holds 60 Hz in WebKitGTK and Chromium.**
  - WebKitGTK with its default renderer dropped 0 of 5 860 frames (two app runs, every drive
    and mode).
  - Chromium dropped 0 of 6 475 (headed and headless).
  - The lead's repeat dropped 0 of 2 931.
- **What the user sees in WebKitGTK updates at about 54–55 Hz.** With the real pointer and the
  default (DMA-BUF) renderer, WebKitGTK gives the page 53.7 to 55.5 pointer events per second.
  So 11 to 14 % of the frames have no new position, and the page redraws 54.4 to 55.1 times
  per second.
  - Without DMA-BUF, in Chromium and in Firefox, the events come at 60 per second.
  - When the page makes its own events, WebKitGTK redraws on every frame (60.4 per second). So
    the drawing is not the limit.
  - Why the DMA-BUF renderer gives fewer pointer events is not known; it was not looked into.

  The lead recomputed every redraw rate of the table from the raw runs with its own code.
- **Headed Firefox misses about 0.5 % of its frames** (36 of 7 151, single frames). It also
  misses them in the `none` mode, where the page draws nothing, so they come from Firefox's
  frame timing under this load, not from the magnifier. Headless Firefox misses none.
- WebKitGTK's frame clock runs at about 62 Hz on the 60 Hz output when the page draws little.
  This is not counted as a drop.
- **Without the DMA-BUF renderer**, the full redraw moves to the CPU: 4 ms instead of under
  1 ms, and the bench goes from 0.008 to 3.3 ms per redraw. The page still holds 60 Hz:
  - 4b-ii dropped 0 of 1 453 frames with the real pointer and 1 of 4 395 page-driven ones;
  - the lead's repeat dropped 0 of 2 932.

  An earlier run, whose results are lost (on the laptop, 2026-10-23), said "about 39 fps"
  without DMA-BUF. On the AMD desktop this does not hold, and the laptop was not measured
  again.
- The clocks step by 1 ms in WebKitGTK and Firefox, so a redraw of "0" means under 1 ms.

## Consequences

- D-1 to D-3 build on the spike's shell, as listed above:
  - the sidecar spawned on a long-lived thread, before the window, with the SIGTERM death
    signal, the token and `--parent-pid`;
  - the shutdown request, then a kill after 5 s.

  `desktop/spike/` stays until D-1 and D-2 have taken what they need.
- **D-1**: keep WebKitGTK's DMA-BUF renderer (the default) for now. It is a trade-off, and D-1
  decides it in the real app:
  - with the default renderer, a full redraw takes under 1 ms, but the page gets only about
    54–55 pointer events per second;
  - without it, the events come at 60 per second, but each full redraw costs about 4 ms of
    CPU.

  D-1 first finds out why the pointer-event rate is lower.
- **D-1** also takes from the review's fixes:
  - the web view's data in the app's own folder (`data_directory`);
  - only the permissions the pages use (here `core:event:allow-listen` and
    `core:event:allow-unlisten`, not `core:event:default`);
  - no `println!` in the shell: on a closed stdout it panics the thread, and the event that
    thread was to send is lost.
- **D-3**:
  - start the frozen sidecar as the shell's direct child, so the parent check is exact;
  - keep the sidecar's settings, queue and log in the platform's folders, with a rotated log,
    not in a temporary folder.
- **D-2**: the PyInstaller options above, and a smoke test of the frozen build for the three
  silent failures. D-2 also decides whether the sidecar ships MediaInfo (pymediainfo is an
  optional extra of the core).
- **D-5**: use Tauri's drag-drop event. Report a file name that cannot be read (U+FFFD), and
  offer the file dialog.
- **F-x (frontend)**: `font: inherit` on buttons, so that PrimeVue's tabs match in every
  engine.
- **F-7 (magnifier)**:
  - Redraw once per `requestAnimationFrame` from the last pointer position.
  - Draw the fitted frame on its own layer, and on a move draw only the loupe and the strips.
    This split was not measured; the `cached` copy tried in the spike cost more in Chromium.
  - Load the frame with `fetch` and `createImageBitmap(blob, { colorSpaceConversion: "none" })`:
    without the option, Chromium converts the PNG's `cICP` (a channel value of 164 reads back
    as 159). This matters for WebView2.
  - Performance tests count frames and redraws over a time, with the real pointer; they do
    not time single draws. A frame rate alone can hide a lower update rate.
- **Core, found by the spike, not fixed here** (for the lead after M3):
  - The preview's tone mapping depends on timing. A frame request before the libplacebo
    Vulkan run test has passed gets zscale + tonemap; a later one gets libplacebo. So the same
    frame has different keys and colours after a restart.
  - A missing definitions data file loads as empty.
  - `naming/parse.py` swallows every guessit error.
  - A failed lifespan start-up prints `Task exception was never retrieved … SystemExit(3)`.
- **Not verified on Windows** (the Windows testing phase of M10,
  [0053](0053-linux-first-windows-testing-phase.md)):
  - the sidecar on Windows: the onedir build, `CREATE_NO_WINDOW`, the Job Object;
  - the parent watch's Windows path (`OpenProcess`, `GetProcessTimes`,
    `WaitForSingleObject`), which is mock-tested only;
  - a kill of the app from Task Manager;
  - WebView2 rendering of PrimeVue and the magnifier, including the `cICP` conversion;
  - drag-and-drop paths in WebView2.
- **Not run on Linux**:
  - drag sources other than Dolphin (a GTK file manager, a browser's download bar);
  - a drop from an XWayland source (Dolphin ran on native Wayland in every case);
  - the magnifier on the laptop (Intel UHD 620), with a real USB mouse, at HiDPI scale 2 or
    full screen, and with a crop-line drag;
  - a first start after a reboot (system libraries cold);
  - on the AMD desktop: the cleanup cases with one mechanism off, the cold start with the
    sidecar in the setup hook, and the error page. These ran on the laptop only.

## Plan changes

None: the plan's choice stands. The D-0 checkboxes of
[07 §D-0](../plan/07-desktop-app.md#d-0-spike-do-this-before-the-frontend-is-far-along) are
ticked for Linux in the same reconciliation as `docs/status.md`.

## Review of the D-0 work, 2026-10-27

A fresh agent (effort `xhigh`) reviewed the D-0 changes in `git diff main...m3-api-spike` and
checked that the M3 demo holds. It had the code and the authors' reports, not the lead's log.
It found 16 issues: 1 blocker, 3 major, 9 minor and 3 nits. The lead checked the blocker and
the majors again before any fix. Two fix tasks fixed them: F1 (`xhigh`; the window and pointer
tools, isolation, the magnifier figures) and F2 (`high`; the Rust shell, the parent watch and
4a's tests). Each fix has a test that fails on the old code, where a test is possible. The lead
repeated 5 mutations of F1's tests and 7 of F2's (Python and Rust); each one failed a test.

F2's five checks that need the real app (R-5, R-10, R-11, R-16, and a quit whose sidecar does
not stop) were refused 40 times by the window guard while the owner's cursor stayed on `DP-1`.
The lead ran them on 2026-10-28 at 07:14 (load 0.28, no movie), when the owner had put the
cursor on `HDMI-A-1`. All three app starts were admitted and opened on `HDMI-A-1`. A stand-in
sidecar that ignores the shutdown request was killed after 5 002 ms, and the app exited 0
(`desktop/spike/README.md`, "Run"; `results/review-fixes-amd-desktop-2026-10-28.out`).

| # | Severity | Finding | Outcome |
|---|----------|---------|---------|
| R-1 | blocker | The window tools could let a new spike window open on `DP-1`, the owner's movie output. `session.js` set `keepAbove` before the window was on `HDMI-A-1`. | Fixed (F1). A session starts a program only when the cursor, KWin's active output and the active window are all on `HDMI-A-1`. `keepAbove` is set only when the window is on `HDMI-A-1`. A window added elsewhere stays transparent, gives the keyboard back, is minimised and stops the session. |
| R-2 | major | A KWin script load that failed still started the program, with no placement. | Fixed (F1): no start after a failed load or a refusal, and the waiting process is reaped. |
| R-3 | major | SIGTERM to `windows run` left the KWin script loaded and `busctl monitor` running. | Fixed (F1): SIGTERM and SIGHUP stop every spike tool as Ctrl+C does. |
| R-4 | major | Magnifier verdict (a) said more than the data: with the real pointer, WebKitGTK redraws only 54–55 times per second. | Fixed (F1): the statistics and the tables give redraws per second, and the verdict says what the user sees. The lead recomputed the rates (WebKitGTK section above). |
| R-5 | minor | The app's WebKitGTK profile was written to the owner's `~/.local/share/org.reframe.spike/`. | Fixed. F1: the scripts give each app run its own XDG folders. F2: the shell puts the web view's data in `<home>/webview/` (Tauri's `data_directory`). In the lead's real-app run with no XDG variables, 12 entries went there and none of the owner's folders changed. The owner had the old folder removed on 2026-10-28. |
| R-6 | minor | The spike sidecars ran the hardware test encodes and libplacebo's Vulkan test on the GPU that the movie used. | Fixed (F1): every spike sidecar has `hardware_tests` off. |
| R-7 | minor | `test_parent.py` passed with `watch.close()` removed from `serve`, with a wrong hard-exit code and with a wrong `/proc` parse. | Fixed (F2). An in-process `serve()` stopped by the shutdown request ignores its parent's end afterwards; the hard-exit code is compared with 70; the younger process runs under a name with `)` and a space. Each of the three changes now fails a test. |
| R-8 | minor | `test_frozen_sidecar.py` passed with MediaInfo missing from the build, and its cleanup case ran no encode. | Fixed (F2). A test reads a bit rate through the bundled MediaInfo (`vfr.mkv`: `mediainfo` 483 043 with it, `unknown` without). The parent-kill case runs a real x265 encode and checks that FFmpeg and the `.part` file are gone. Builds without MediaInfo, guessit's data, the definitions, the tools manifest or the parent watch each fail a test. |
| R-9 | minor (plausible) | The parent watch accepted a pid reused in the same clock tick. | Fixed (F2; 0054 "Follow-up (review)"). A live ancestor is accepted exactly; any other pid must have started one clock tick before the server. A child of `timeout` shares its parent's start tick in 198 of 200 runs, so the tick alone would refuse real parents. Still open: a parent above the direct parent that ended, and whose pid was reused, between two forks of the start-up. D-3 starts the sidecar as the shell's direct child. |
| R-10 | minor | `snapshot` wrote to any path the page gave, and the capability allowed `emit`. | Fixed (F2). A snapshot is written only below `REFRAME_SPIKE_SNAPSHOT_DIR`: no `..`, no symlink out of it, and the file is opened with `O_NOFOLLOW` (three Rust tests). The capability is `core:event:allow-listen` and `core:event:allow-unlisten`. In the lead's real-app run, both pages still registered their listeners. |
| R-11 | minor (plausible) | The default spike home `$TMPDIR/reframe-spike-<pid>` was predictable and kept after exit. | Fixed (F2). The default home is a new `$TMPDIR/reframe-spike-<16 random hex digits>`, made with mode 0700 by a call that fails when the name exists. It is kept after the exit, because the error page names its log. In the lead's real-app run it was `0o700` and owned by the user. |
| R-12 | minor | 4a's laptop numbers have no raw data in `results/`. | Fixed (F2). `cold_start` and `cleanup` write their raw output and the load to `results/` by default. The lead's AMD runs are committed there, and F2 recomputed every AMD figure from them. The laptop runs cannot be recomputed (Cold start, above). |
| R-13 | minor | Spike tests that passed while the code was wrong (the p95 rank; `session.js` was not tested). | Fixed (F1): a node test of `session.js` against a fake KWin, and a p95 case. |
| R-14 | nit | Wording; each run's first interval counted. | Fixed (F1): the first interval is left out, and every figure was computed again. |
| R-15 | nit | Leftovers: unused launcher folders, a kill by pid alone, waits that did not kill. | Fixed (F1). |
| R-16 | nit | `page_health` is printed before the frame is painted; a `println!` would panic on a closed stdout. | Fixed (F2). The shell drops a line written to a closed stdout. In the lead's real-app run, the app built before the fix panicked in its `tokio-rt-worker` thread (`failed printing to stdout: Broken pipe`); the new one ran on and quit with 0. The README says that `page_health` can come up to one frame (16.7 ms) early. |

**The R-1 incident.** In the reviewer's own run, at 21:44:47.671, KWin added a transparent app
window on `DP-1`. The window took the keyboard from the movie player (Haruna) for 2.2 ms. An
earlier window, added on `HDMI-A-1` at 21:44:45.392, took it for 2.9 ms. The times come from the
owner's `foreground_booster` log in the user journal. No other spike window took the keyboard
from a movie player that day. Every window of the lead's runs, and the one of F1's run, was
added on `HDMI-A-1`.

**What the fix cannot prevent:**

- **Every new window still takes the keyboard for a few ms**, also on `HDMI-A-1`. KWin 6.8
  activates a new window before a script hears of it, at the default focus-stealing level
  ("Low"). Only a persistent setting or a window rule could stop that, and none was changed.
  In F1's run it took 3.9 ms, from VS Code.
- **The window can still open elsewhere** if the cursor or the keyboard moves to `DP-1`
  between the check and KWin adding the window. In F1's run that gap was 543 ms. Such a window
  is hidden, and the session stops.
- **A window whose class is not the session's is admitted but neither placed nor watched.** In
  the lead's run, the app built before the fixes (class `reframe-spike-old`) opened where KWin
  put it, on `HDMI-A-1` because the cursor was there. It kept the keyboard from VS Code for
  1.64 s, until it quit.

No spike window took the keyboard from anything but VS Code after the R-1 incident (the
owner's journal, 2026-10-27 22:10 to 2026-10-28 07:15).

**The M3 demo held** in the reviewer's headless run (`multitrack.mkv`):

- 79 operations, and no route missing from the OpenAPI document;
- `gen-api.sh --check` green;
- `job.progress` to 100 %, then `done`;
- SIGINT → exit 130.

**The lead's M3 demo** (2026-10-28 00:40, AMD desktop, after F2's merge, with
`scripts/gen-api.sh --check` green on the same tree). It ran
`reframe-server --mode web --host 127.0.0.1 --auth none --media-root … --output-root …` with
temporary config, data and cache folders, hardware tests off and the system FFmpeg (n9.0.2):

- `GET /api/health` 200 after 0.72 s.
- `GET /api/openapi.json`: OpenAPI 3.1.0, 71 paths, 79 operations, 79 unique operation IDs.
  The app's own routes (walked through the included routers) are the same 79. None is missing
  from the document, and the document has no operation without a route. A plain count of the
  route decorators in the server's source also gives 79 (4 DELETE, 24 GET, 46 POST, 5 PUT) and
  1 WebSocket route, `/api/events`. `/api/docs` is the docs page of `/api/openapi.json`.
- `WS /api/events`: auth, then `hello`. `hdr10-4k.mkv` (3840×2160, `yuv420p10le`) was probed
  (`POST /api/sources`, then the task). The draft had the default size (fit 1920×1080) and an
  `output.folder_required` error, because web mode takes only an output inside an output root.
  With the output there, the job was queued and started: libx265 `slow`, 4.9 s.
- The socket carried `job.state` waiting → running → done, and 13 `job.progress` events for
  the job (13.3 % at 7.45 fps, then 100 % in the finalize step). Event numbers ran 1 to 27
  with no gap.
- The output was HEVC 1920×1080 `yuv420p10le`, 5.005 s.
- SIGINT → exit 130 after 0.26 s. The temporary folder was removed.
