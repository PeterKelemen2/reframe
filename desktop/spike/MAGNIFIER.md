# D-0: canvas crop magnifier frame times (Linux)

Task 4b-ii, 2026-10-27, on the owner's AMD desktop (Ryzen 5 5600, Radeon RX 7600, KDE Plasma
6.8.1 on Wayland, WebKitGTK 2.54.2, Playwright 1.64.1 with Chromium 156.0.8078.4 and Firefox
157.0). Every window was on `HDMI-A-1` (60 Hz) and was read back there. A movie played on
`DP-1` (165 Hz) during every run. Tool behaviour these results rely on: `testdata/README.md`,
"D-0 (4b-ii)".

## How to run it

Build first (the frozen sidecar, the UI and the app; see `README.md`). Then, from the
repository root:

```sh
uv run python -m desktop.spike.scripts.magnifier_check frame-route            # headless
uv run python -m desktop.spike.scripts.magnifier_check browsers --headless    # no window
uv run python -m desktop.spike.scripts.magnifier_check app                    # WebKitGTK, window + real pointer
uv run python -m desktop.spike.scripts.magnifier_check app --no-dmabuf        # WEBKIT_DISABLE_DMABUF_RENDERER=1
uv run python -m desktop.spike.scripts.magnifier_check browsers --headed      # windows + real pointer
uv run python -m desktop.spike.scripts.magnifier_check summary                # the table below
```

`--tag=-repeat` writes a repeat to a file of its own. Each case writes
`results/magnifier-<case>.json`: the page's records, the raw frame intervals and redraw times
of every run, their statistics, the load and the refresh rates before, between and after, the
windows as read back, and a summary of the pointer's moves. Screenshots:
`results/magnifier-webkitgtk.png` (WebKitGTK's own snapshot of the web view, `spike.js`
`snapshot()`), `magnifier-chromium.png` and `magnifier-firefox.png` (Playwright's screenshot of
the page, headed, at the end).

Every sidecar, the app and each browser gets temporary folders (`REFRAME_*_DIR`,
`XDG_CACHE_HOME`, Playwright's own temporary profile). The app run takes about 60 s, of which
the real pointer moves for about 14 s (calibration and three 4 s runs).

## What the page draws

`ui/src/pages/MagnifierPage.vue` (`REFRAME_SPIKE_PAGE=magnifier`, or `?page=magnifier` in a
browser), with `ui/src/magnifier/draw.js` and `run.js`. The viewport is 1280×800 at a device
pixel ratio of 1.

- The page gets a source id (in a browser it probes `?source=`; in the app the check script
  probes `hdr10-4k.mkv` through the sidecar's API and the page takes it from `GET /api/sources`),
  asks `POST /api/preview/frames` for the frame at 2.5 s, fetches the signed PNG URL with
  `fetch` and decodes it with `createImageBitmap`. The bitmap is 3840×2160 in every engine.
- Main canvas, 860×484: the whole frame scaled to fit (smoothing on), the removed area tinted,
  the crop rectangle (140 / 140 / 96 / 96), and a round loupe (radius 80 px) with the 40×40
  source pixels under the cursor at 4×, `imageSmoothingEnabled = false`.
- Four edge strips at 4×, `imageSmoothingEnabled = false`: top and bottom 372×88 (93 source
  columns around the cursor's column, 11 rows on each side of the crop line), left and right
  88×240 (60 source rows around the cursor's row, 11 columns on each side). The removed side
  is tinted, and the crop line is drawn at the pixel boundary.
- A redraw draws all five canvases. A pointer event only stores the position; the frame loop
  (`requestAnimationFrame`) redraws once per frame when the position changed.
- Modes: `full` scales the 4K bitmap again on every redraw; `cached` draws a copy of the fitted
  frame made once; `none` keeps the frame loop and the events but draws nothing (each engine's
  own frame timing, for comparison).

Per run (4 s each) the page records every frame interval (the difference between consecutive
`requestAnimationFrame` timestamps), the time of each redraw (`performance.now()` around the
draw), and the pointer events (count, `isTrusted`, `pointerType`). A frame is dropped when its
interval is longer than 1.5 periods of 60 Hz (25 ms); "missed" counts the periods it skipped.

Once per page load, a bench draws 120 redraws back to back on canvases of their own, and 60
redraws each followed by a one-pixel `getImageData` of all five canvases. The read-back makes
the time include the drawing that a GPU canvas otherwise does later. The shown canvases are
never read: a read can make a browser stop accelerating a canvas.

## The frame route's answer

`uv run python -m desktop.spike.scripts.magnifier_check frame-route` → `results/magnifier-frame-route.json`:

- `POST /api/preview/frames` with `{"source_id": …, "timestamps": [2.5]}` waits for the frame
  task, then answers 200 with JSON
  `{"frames": [{"key", "kind": "source", "timestamp": 2.5, "width": 3840, "height": 2160,
  "cached": false, "url": "/api/preview/frames/<key>.png?exp=…&sig=…"}], "notes": ["The source
  is HDR10: a PNG cannot hold HDR, so the frames are tone mapped to SDR for display with …"]}`.
  The answer has no bytes in it: it gives a signed URL that expires (`exp`, `sig`) and that
  needs no token. The first request took 0.517 s (FFmpeg); the same request again 0.004 s
  (`cached: true`).
- `GET <url>`: 200, `image/png`, an `ETag` (the key), 1 169 110 bytes (zscale + tonemap) or
  2 559 598 bytes (libplacebo). `ffprobe` of the downloaded file: `png`, **3840×2160**,
  `rgb24`. The PNG has `cICP` (BT.709 primaries and transfer, full range), `cHRM` and `gAMA`
  chunks. Without the signature the same path gives 401 (`auth.required`).
- In the pages (all engines): the frames route took 0.51–0.71 s, the PNG fetch 7–12 ms and
  `createImageBitmap` 34–71 ms.

**The tone mapping is not the same in every run.** Of the ten sidecars whose results are
kept, six used zscale + tonemap and four used libplacebo, for the same source and
timestamp, with different frame keys. `usable_filter` takes `libplacebo` only after its Vulkan
run test has passed, so the first frame request after a start races that test. The timings do
not depend on it (the same size of bitmap, the same draw calls). But it changes the colours of
the screenshots: compare them only with the frame each one shows
(`frame.answer.notes` in each JSON).

## Numbers

Interval and redraw: median / 95th percentile / worst, in ms. "fps" is the frame count divided
by the sum of the intervals. "Dropped" counts intervals > 25 ms (with the missed periods in
brackets) out of all the frames of the runs. "events/s" is the pointer events that reached the
page, per run. Refresh rate: `HDMI-A-1` 60 Hz in every run (`kscreen-doctor -o`, the current
mode). Headless browsers have no output; they draw at 60 frames per second. "Load": the 1-minute
load average before → after the case (`/proc/loadavg`).

| Engine, case | Drive / mode | Interval ms | fps | Redraw ms | Dropped | Runs | events/s | Hz | Load |
|---|---|---|---|---|---|---|---|---|---|
| WebKitGTK | real / full | 16.0 / 17 / 19 | 62.2 | 0 / 1 / 1 | 0 (0) of 744 | 3 | 54–55 | 60 | 2.48 → 1.82 |
| WebKitGTK | page / full | 17 / 19 / 21 | 60.36 | 0 / 1 / 3 | 0 (0) of 725 | 3 | 84 | 60 | 2.48 → 1.82 |
| WebKitGTK | page / cached | 16 / 18 / 20 | 60.48 | 0 / 1 / 2 | 0 (0) of 726 | 3 | 84 | 60 | 2.48 → 1.82 |
| WebKitGTK | page / none | 16 / 17 / 19 | 62.19 | 0 / 0 / 1 | 0 (0) of 747 | 3 | 84 | 60 | 2.48 → 1.82 |
| WebKitGTK, repeat | real / full | 16 / 17 / 19 | 62.17 | 0 / 1 / 2 | 0 (0) of 744 | 3 | 54–55 | 60 | 2.08 → 2.06 |
| WebKitGTK, repeat | page / full | 17 / 18 / 21 | 60.36 | 0 / 1 / 2 | 0 (0) of 725 | 3 | 84 | 60 | 2.08 → 2.06 |
| WebKitGTK, no DMA-BUF | real / full | 16 / 18 / 24 | 60.87 | 4 / 5 / 7 | 0 (0) of 732 | 3 | 60–61 | 60 | 2.29 → 2.41 |
| WebKitGTK, no DMA-BUF | page / full | 16 / 18 / 20 | 60.57 | 4 / 5 / 7 | 0 (0) of 728 | 3 | 80–81 | 60 | 2.29 → 2.41 |
| WebKitGTK, no DMA-BUF | page / cached | 16 / 18 / 22 | 60.55 | 1 / 1 / 3 | 0 (0) of 728 | 3 | 84 | 60 | 2.29 → 2.41 |
| WebKitGTK, no DMA-BUF | page / none | 16 / 17 / 19 | 62.4 | 0 / 0 / 0 | 0 (0) of 750 | 3 | 84 | 60 | 2.29 → 2.41 |
| WebKitGTK, no DMA-BUF, repeat | real / full | 16 / 19 / 23 | 60.51 | 4 / 5 / 7 | 0 (0) of 727 | 3 | 60–61 | 60 | 2.37 → 1.56 |
| WebKitGTK, no DMA-BUF, repeat | page / full | 17 / 18 / 23 | 60.52 | 4 / 5 / 6 | 0 (0) of 728 | 3 | 81 | 60 | 2.37 → 1.56 |
| WebKitGTK, no DMA-BUF, repeat | page / cached | 16 / 18 / 26 | 60.65 | 1 / 1 / 2 | 1 (1) of 730 | 3 | 84 | 60 | 2.37 → 1.56 |
| Chromium headed | real / full | 16.7 / 16.8 / 17.1 | 60.0 | 0.0 / 0.1 / 0.2 | 0 (0) of 720 | 3 | 60 | 60 | 2.99 → 1.61 |
| Chromium headed | playwright / full | 16.7 / 16.7 / 17.3 | 60.0 | 0.0 / 0.1 / 0.2 | 0 (0) of 721 | 3 | 60 | 60 | 2.99 → 1.61 |
| Chromium headed | page / full | 16.7 / 16.8 / 16.8 | 60.0 | 0.0 / 0.1 / 0.2 | 0 (0) of 723 | 3 | 123 | 60 | 2.99 → 1.61 |
| Chromium headed | page / cached | 16.7 / 16.8 / 16.8 | 60.0 | 0.1 / 0.2 / 0.4 | 0 (0) of 723 | 3 | 123 | 60 | 2.99 → 1.61 |
| Chromium headed | page / none | 16.7 / 16.7 / 16.8 | 60.0 | 0.0 / 0 / 0.8 | 0 (0) of 723 | 3 | 123 | 60 | 2.99 → 1.61 |
| Chromium headless | playwright / full | 16.7 / 16.7 / 16.8 | 60.0 | 0.0 / 0.1 / 0.2 | 0 (0) of 723 | 3 | 60 | (60) | 4.35 → 2.89 |
| Chromium headless | page / full | 16.7 / 16.7 / 16.8 | 60.0 | 0 / 0.1 / 2.2 | 0 (0) of 723 | 3 | 119–120 | (60) | 4.35 → 2.89 |
| Chromium headless | page / cached | 16.7 / 16.7 / 16.8 | 60.0 | 0.5 / 0.8 / 1.9 | 0 (0) of 723 | 3 | 120 | (60) | 4.35 → 2.89 |
| Firefox headed | real / full | 17 / 17 / 34 | 59.41 | 0 / 1 / 1 | 7 (7) of 715 | 3 | 59–60 | 60 | 1.48 → 3.14 |
| Firefox headed | playwright / full | 17 / 17 / 34 | 59.59 | 0 / 1 / 1 | 5 (5) of 717 | 3 | 59–60 | 60 | 1.48 → 3.14 |
| Firefox headed | page / full | 17 / 17 / 34 | 60.05 | 0 / 1 / 1 | 1 (1) of 720 | 3 | 121–122 | 60 | 1.48 → 3.14 |
| Firefox headed | page / cached | 17 / 17 / 33 | 59.75 | 0 / 1 / 2 | 3 (3) of 717 | 3 | 121–122 | 60 | 1.48 → 3.14 |
| Firefox headed | page / none | 17 / 17 / 33 | 60.15 | 0 / 0 / 1 | 1 (1) of 722 | 3 | 121 | 60 | 1.48 → 3.14 |
| Firefox headed, repeat | real / full | 17 / 17 / 34 | 59.83 | 0 / 1 / 1 | 2 (2) of 720 | 3 | 60 | 60 | 2.82 → 2.27 |
| Firefox headed, repeat | playwright / full | 17 / 17 / 34 | 59.25 | 0 / 1 / 2 | 9 (9) of 713 | 3 | 59–60 | 60 | 2.82 → 2.27 |
| Firefox headed, repeat | page / full | 17 / 17 / 17 | 60.09 | 0 / 1 / 1 | 0 (0) of 721 | 3 | 122 | 60 | 2.82 → 2.27 |
| Firefox headed, repeat | page / none | 17 / 17 / 34 | 59.98 | 0 / 0 / 1 | 3 (3) of 720 | 3 | 121–123 | 60 | 2.82 → 2.27 |
| Firefox headless | playwright / full | 17.06 / 17.1 / 17.5 | 60.01 | 2 / 3 / 5 | 0 (0) of 720 | 3 | 60 | (60) | 2.89 → 2.53 |
| Firefox headless | page / full | 17.06 / 17.08 / 17.28 | 60.26 | 2 / 3 / 4 | 0 (0) of 723 | 3 | 120 | (60) | 2.89 → 2.53 |

The other rows (Chromium headless `none`, Firefox headless `cached` and `none`, the repeats'
`cached`) are in `summary`'s output and the JSON files; none of them has a dropped frame except
Firefox headed repeat `cached` (5 of 716).

**Clocks.** `performance.now()` and the frame timestamps step by 1 ms in WebKitGTK and
Firefox, and by 0.1 ms in Chromium. So a redraw of "0" ms there means less than 1 ms. The fps
column is still exact: a sum of intervals is exact to one step.

**The redraw bench** (ms per redraw; queued = without a read, read back = with a one-pixel read
of each of the five canvases):

| Engine | full, queued | full, read back | cached, queued | cached, read back |
|---|---|---|---|---|
| WebKitGTK | 0.008–0.017 | 1.05 | 0.125 | 0.73–0.77 |
| WebKitGTK, no DMA-BUF | 3.31–3.33 | 3.32–3.45 | 0.48–0.52 | 0.50 |
| Chromium headed | 0.024 | 5.40 | 1.79 | 3.93 |
| Chromium headless | 0.013 | 13.7 | 0.32 | 2.46 |
| Firefox headed | 0.008–0.025 | 3.42–3.92 | 0–0.008 | 3.33–3.67 |
| Firefox headless | 0.99 | 0.98 | 0.23 | 0.25 |

The read-back times include five GPU-to-CPU reads per redraw. They are an upper bound of the
drawing work, not the cost of one frame.

**Load.** The 1-minute load average was 1.5 to 4.4. The top CPU users over half a second
(`top -b -n 2 -d 0.5`; `ps` gives the average since each process started) were, in each case:
the owner's VS Code (`code`, 37–161 %), `kwin_wayland` 16–24 %, the owner's Firefox 8–16 %, and
the movie player `jellyfin-desktop` 4–8 %. The 4.35 at the start of the headless Chromium case
came right after a Tauri build. The headless numbers have no dropped frame, so they were not
repeated.

## How the pointer moved

All cases follow the same path: an ellipse centred on the main canvas, with semi-axes
0.4 × 860 = 344 px and 0.4 × 484 = 194 px, one turn every 2 s (about 870 px/s). The point is
computed from the time since the run started, so the speed does not depend on the event rate.
Each run starts with the first move over the main canvas and lasts 4 s.

- **Real pointer** (`real`; the app, headed Chromium and headed Firefox): an absolute pointer
  device made with `/dev/uinput` (`scripts/pointer.py`). One move every 8 ms (about 125 per
  second were sent: 501 to 506 per run). KWin read back each move at its target before the next
  one (median 0.2–0.3 ms, worst 3–18 ms; 1512 to 1522 moves per case, every one at its target).
  Before the runs the pointer moves onto the page's empty background below the edge strips.
  There the page logs the client coordinates, which give the window's offset (app: 40, 68;
  Chromium: 40, 127; Firefox: 40, 125). A second point checks the offset. Between runs the
  pointer rests in the page's bottom bar. While a window opens and during the other cases, it
  waits at 960, 1040 on `HDMI-A-1`, below every window. No button and no key was pressed.
- **Playwright** (`playwright`; Chromium and Firefox, headed and headless): `page.mouse.move`
  to each point, paced at 8 ms. Each call waits until the browser has handled the event, so the
  rate settled at 60 per second (one per frame) in both engines.
- **Page-driven** (`page`; every engine, the only synthetic case in WebKitGTK): the page
  dispatches a `PointerEvent("pointermove")` on the canvas from a `setTimeout` loop of 8 ms
  (`isTrusted` false). It reached about 84 events per second in WebKitGTK (its timers come
  later than 8 ms) and about 120 in Chromium and Firefox.

Events that reach the page with the real pointer: WebKitGTK 54–55 per second (60–61 without the
DMA-BUF renderer), Chromium and Firefox 60. Each engine merges the motion events to about one
per frame. In WebKitGTK at 62 fps, about 12 % of the frames had no new position and so no
redraw.

What this does not measure:

- **Input latency**: the time from a move to the frame that shows it. Nothing here times it.
- **Presentation**: the intervals are the engine's own frame clock (`requestAnimationFrame`
  timestamps). They do not show when KWin put a frame on `HDMI-A-1`, or whether a frame was
  shown at all. WebKitGTK's clock runs at 62.2 Hz, faster than the 60 Hz output, so about two
  frames per second are drawn but cannot all be shown. That is not counted as a drop.
- **vsync with the movie**: the movie's 165 Hz output and its decoder share the GPU. The
  numbers are taken under that load, but they do not show how the movie's own frames fared
  (nobody watched for stutter).
- **GPU time** of a redraw: the redraw column is the time to queue the drawing on the main
  thread. The bench's read-back gives an upper bound.
- **Real input hardware**: uinput events go through KWin like a mouse's, but there is no USB
  polling or device jitter, and the moves are perfectly even.
- **The real F-7 sizes**: one 1280×800 viewport at scale 1. No HiDPI (scale 2 has 4× the
  pixels per canvas), no full-screen window, no drag of a crop line, no frame change.
- **The laptop**: the lost run was on the Intel UHD 620 laptop, which is packed. Nothing here
  was measured on it.

## The two claims of the lost run

**(a) "The magnifier holds 60 Hz in all three engines."** WebKitGTK and Chromium: **holds**.
Firefox (headed): **holds only with a qualification**.

- WebKitGTK: 0 dropped frames of 5 884 (two app runs: real, page full, page cached, page none),
  worst interval 21 ms. The frame rate is 60.4 to 62.2 fps.
- Chromium headed and headless: 0 dropped frames of 6 502, worst 17.3 ms, exactly 60.0 fps.
- Firefox headed: median 17 ms (59.3 to 60.2 fps), but 36 single missed frames (33–34 ms) of
  7 181 (0.5 %), 0 to 9 per 720 frames, in every drive and mode. They also come in `none`, where the page draws
  nothing, and the redraw takes at most 3 ms. The repeat gave the same picture. So they come
  from Firefox's own frame timing on this desktop under this load, not from the magnifier.
  Headless Firefox drops none.

Command: `magnifier_check app`, `app --tag=-repeat`, `browsers --headed`,
`browsers --headed --engines firefox --tag=-repeat`, `browsers --headless`; then `summary`
(the table above).

**(b) "`WEBKIT_DISABLE_DMABUF_RENDERER=1` drops a full redraw in WebKitGTK to about 39 fps."**
**Does not hold** on this machine. Without the DMA-BUF renderer the full redraw is done on the
CPU: the redraw takes 4 ms (median; worst 7 ms) instead of under 1 ms, and the bench goes from
0.008 to 3.3 ms per queued redraw. The variable takes effect. But the page still runs at 60.5
to 60.9 fps, with 0 dropped frames under the real pointer in two runs (1 459 frames), and 1 in
the 4 413 page-driven frames (the `cached` mode, 26 ms). On the laptop's slower CPU and GPU it
may be different: not measured.

Command: `magnifier_check app --no-dmabuf` and `app --no-dmabuf --tag=-repeat`, compared with
`app` and `app --tag=-repeat`.

## What F-7 and D-1 should take from this

- **A canvas magnifier with a 4K bitmap is cheap in every engine** at this size: scaling the
  whole 3840×2160 bitmap again on every pointer move costs under 1 ms on a GPU canvas. On
  WebKitGTK's CPU path it costs 4 ms. No engine needs a tile or worker scheme for it. Draw
  once per `requestAnimationFrame` from the last pointer position: no engine delivers more than
  one real pointer event per frame anyway.
- **Do not redraw the big image on every move.** Draw the fitted frame on its own canvas when
  the frame, the crop or the size changes, and the loupe and the strips on the moves. The
  `cached` mode (a pre-scaled copy, drawn again) is not that: it saved time on the CPU path
  (1 ms against 4 ms), but in headed Chromium it cost more to queue (1.8 ms against 0.02 ms). A
  separate layer was not measured.
- **Load the frame with `fetch` + `createImageBitmap`.** It works under the app's
  Content-Security-Policy in all three engines, and the canvas stays readable (not tainted),
  which the luma check of `CropCheckGrid` needs. Use
  `createImageBitmap(blob, { colorSpaceConversion: "none" })`. Chromium otherwise converts the
  PNG's `cICP` BT.709 transfer to sRGB (a channel of 164 reads back as 159), so the magnifier
  would not show the file's pixel values. Firefox does not convert in either case. This matters
  for WebView2 (Chromium) on Windows.
- **Per-frame budgets need care in WebKitGTK and Firefox**: their clocks step by 1 ms. A
  performance test of F-7 should count frames over a time, or use read-backs, not time single
  draws.
- **WebKitGTK's frame clock is not the output's vblank** (62.2 Hz on a 60 Hz output when the
  page draws little). An animation should use the frame timestamp, not count frames.
- **The preview's tone mapping depends on timing** (zscale before the libplacebo run test has
  passed, libplacebo after). The same frame can look different after a restart, and the cache
  holds both. This is for the core (preview / capabilities), not for F-7: a question for the
  lead.
- **D-1**: the DMA-BUF renderer is no reason to set `WEBKIT_DISABLE_DMABUF_RENDERER` for the
  magnifier's sake. Even without it this page holds 60 Hz here. Leave the default, and keep the
  variable as a workaround for GPU driver trouble only.
