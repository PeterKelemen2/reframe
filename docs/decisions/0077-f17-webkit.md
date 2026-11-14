# 0077 — F-17: the flows and the accessibility gate in WebKit

- Status: accepted
- Date: 2026-11-14
- Steps: F-17 (F-16)

## Context

[06 §F-17](../plan/06-web-app.md#f-17-end-to-end-tests): "M10 runs all five in Chromium and
WebKit". [0076](0076-f16-i18n-and-accessibility-audit.md) item 5 left the gate in WebKit to F-17.
M4 to F-16 ran the e2e suite in headless Chromium and Firefox only, because WebKit was not in the
browser cache ([0063](0063-m4-frontend-mvp.md), "Task M").

WebKit matters for the desktop app as well as for Safari: on Linux, Tauri renders the UI in
WebKitGTK ([0001](0001-desktop-shell.md)). Playwright's WebKit (build 2370 for
`@playwright/test` 1.64.1) is a WPE/GTK MiniBrowser built for Ubuntu 24.04.

**WebKit on this host (CachyOS).** Playwright downloads the Ubuntu 24.04 build ("your OS is not
officially supported") and refuses to start it: ICU 74, `libxml2.so.2`, flite and
`libjxl.so.0.8` are missing (`ldd` on `minibrowser-wpe/lib/libWPEWebKit-2.0.so.1`). Installed
by the owner on 2026-11-14: `libxml2-legacy`, `flite`, `libbacktrace` (repositories), `icu74` and
`flite-voices-extra` (AUR; Arch's `flite` leaves out six voice libraries that WebKit links:
`cmu_grapheme_lang`, `cmu_grapheme_lex`, `cmu_time_awb`, `cmu_us_awb`, `cmu_us_kal`,
`cmu_us_rms`). No package has libjxl 0.8: a link `libjxl.so.0.8 → /usr/lib/libjxl.so.0.12` in
Playwright's own `minibrowser-wpe/lib/` and `minibrowser-gtk/lib/` (the bundle puts its `lib/`
first). The app shows no JPEG XL image. Then `webkit.launch()` works with host validation on.

**The first run** (`npx playwright test --project webkit`, 2026-11-14, 12.4 min): 87 passed,
12 failed, from five causes:

| | Failure | Tests |
|---|---|---|
| A | focus ring of the preview strip's thumbnail: 195 (light) / 196 (dark) pixels at 3:1, 218 needed (`indicator-contrast`) | gate: `crop-manual`, `preview-frames`, `split-compare`, `preview-clip`, `toast`, `status-error`, `group` |
| B | a focused text field is covered (`obscured`): the Tags tab's template fields, the naming field overrides | gate: `tags`, `toast`, `status-error`, `summary`, `group` |
| C | typing `fr` in the language picker chooses Fijian (`fj`), not French | `keyboard-tracks.spec.ts` "the language picker reopens on the chosen language…" |
| D | the magnifier's strips at 4×: `tinted×20 other×74 line×4 other×94`, expected `tinted×47 line×2 kept×47` (smoothed) | flow 4 |
| E | the Range popover's end chapter Select is never stable and is detached; the test times out | flow 5 |

## Decision

1. `playwright.config.ts` has a third project `webkit` (`devices['Desktop Safari']`, headless,
   one worker, its own server on the third port). **Firefox stays** (owner, 2026-11-14): it
   passes and finds other defects. The gate's `Browser` type has `webkit`; a known-list entry
   without `browser` is expected in every browser.
2. CI installs `chromium firefox webkit` with `--with-deps` on `ubuntu-latest` (WebKit's own
   platform), so CI needs none of the host steps above.
3. Each failure is fixed in the app, or in the gate when the gate measures WebKit wrongly
   (shown with the rendered pixels or the DOM, not assumed). A known-list entry is left only
   with a reason in this record.
4. Done when: 06 §F-17 (all five flows in Chromium and WebKit) and the gate in WebKit with every
   known list empty; the whole suite passes twice in a row in all three browsers.

## Consequences

- The e2e run takes about three times as long as Chromium alone; the CI job's timeout is checked
  against the measured time.
- A Playwright upgrade that changes the WebKit build needs the libjxl link again on this host
  (Arch packages do not cover it).
- Headless WebKit on Linux is WPE, not WebKitGTK: close to the desktop's renderer, not the same.
  The desktop smoke test (D-9) still runs the real WebKitGTK.

## Plan changes

None: the plan already asks for WebKit. Firefox staying is an addition, not a change.

## Task W1: the picture area (A, D)

Both causes come from one difference: Playwright's `Desktop Safari` profile has
`deviceScaleFactor: 2`, and `Desktop Chrome` and `Desktop Firefox` have 1. WebKit at
`deviceScaleFactor: 1` passes flow 4 and the gate's thumbnail check without a change.

**D (flow 4): the test read a 2× canvas as 1×, and the app squeezed the canvas.** The
magnifier sizes its canvases at `devicePixelRatio` (`prepareCanvas`), so in WebKit the top
strip is 896 × 192 canvas pixels for 448 × 96 CSS pixels. Flow 4 took one canvas pixel per CSS
pixel: it read 192 rows as 96 and found `tinted×20 other×74 line×4 other×94`. The pixels were
not smoothed (`line×4` is the 2 CSS px line at ratio 2). Chromium and Firefox at
`deviceScaleFactor: 2` failed flow 4 in the same way. Flow 4 now reads the strips at the page's
ratio (`tinted×94 line×4 kept×94` in WebKit).

While checking, a real defect showed in every browser: PrimeVue's base style sets
`box-sizing: border-box` on every element, so the strip canvas's 1 px border was inside its CSS
size. A 448 × 96 canvas was shown in a 446 × 94 box, and the browser resampled the zoomed
pixels and the crop line (rows that mix two source rows in a device-scale screenshot). The canvas
is `content-box` now: the screenshot shows 4 px blocks (8 device px in WebKit) and a 2 px line
(4 device px) with no mixed rows. Flow 4 fails when a canvas's pixels are not its CSS box times
the ratio.

Mutations (flow 4): `border-box` back on the canvas fails in Chromium
(`448×96 canvas in a 446×94 box at ×1`) and WebKit (`896×192 … at ×2`);
`imageSmoothingEnabled = true` fails in WebKit
(`tinted×47 other×26 tinted×5 other×16 line×4 other×94`).

**A (the thumbnail's ring): the gate measures WebKit wrongly; the ring is complete.** The gate
takes its focused and unfocused pictures with `page.screenshot({ scale: 'css' })`. Chromium and
Firefox draw that picture at CSS scale. WebKit takes device pixels and scales them down. The
thumbnail's top is at y = 463.31, so its 2 px outline (offset 2 px) covers device rows 919–922,
which is CSS rows 459.5–461.5. Scaled down, that is one full row and two half rows, and the half
rows do not reach 3:1. The gate also leaves out the pixels near the next thumbnail (the stop that
has the focus then), which removes the ring's right side. The count is 195 of 218. In a
device-scale screenshot of WebKit, the ring is a solid 4 device px band on every side (2166
device px at 3:1). Chromium and Firefox at `deviceScaleFactor: 2` pass, because their CSS-scale
picture is drawn at CSS scale. No app change: the ring that a Safari user sees is complete.

The fix belongs to the gate (W2's files, given to the lead as a diff): take the pictures at
`scale: 'device'` and count in device pixels, with the need multiplied by the ratio squared. With
that diff, the four picture screens passed in WebKit twice, and the gate's thumbnail findings left
`toast`, `status-error` and `group` (only B is left on them). The picture area passed in
Chromium and Firefox (at ratio 1 the count is the same). With the diff, the gate still finds a
low-contrast ring (`#c8c8c8`: 0 of 871 px) and a ring clipped by `overflow: hidden` on the
strip (864 of 871 px) in WebKit. The other way is `deviceScaleFactor: 1` for the `webkit`
project. That stops testing at the ratio that Safari users have, so it is not recommended.

`known/picture.ts` stays empty.

## Task W2: focus and the tracks area (B, C)

(Filled by W2.)

## Task W3: the Range popover (E)

**Cause: a real defect, in Chromium and WebKit, which the fast Playwright click hid.** PrimeVue's
`Select` chooses an option on `mousedown`, hides its list a task later, and sets
`pointer-events: none` on the list while it leaves. The release then lands on what is under the
list (here the popover's own text), and the browser sends the `click` to the nearest element
under both the press and the release: `<body>`. PrimeVue's `Popover` takes a click on `<body>`
for a click outside and closes. The end chapter `Select` then moves (the popover's leave
animation: "element is not stable") and goes ("detached").

Evidence (headless, a probe with capture listeners on `chapters.mkv`):

| | press → release | release on | click on | popover |
|---|---|---|---|---|
| WebKit, Playwright click | 62 ms | `P.range-popover__length` | `BODY` | closed |
| Chromium, Playwright click | 11 ms | the option | the option | open |
| Firefox, Playwright click | 22 ms | the option `LI` | the option `LI` | open |
| Chromium, press of 120 ms | 131 ms | `P.range-popover__length` | `BODY` | closed |
| WebKit, press of 120 ms | 162 ms | `P.range-popover__length` | `BODY` | closed |
| Firefox, press of 120 ms | 139 ms | the option `LI` | the option `LI` | open |

WebKit's Playwright click is a race (another probe run released after 48 ms, on the option).
A person's press is longer than the list's hide (one task), so a mouse user lost the popover
after each chapter pick in Chromium, Safari and the Linux desktop app (WebKitGTK). Only Firefox
still sends the release to the leaving list. The keyboard was never affected.

**Fix** (`RangeSelector.vue`): a press in a chapter list drops the click of its release (a
window capture listener for that one click, removed a task after the release). The list needs
no click: the option is already chosen. PrimeVue's own way (`OverlayEventBus` `overlay-click`,
which `Popover` takes as a click inside) has no type declarations and is not in PrimeVue's
`exports`, so it is not used. `appendTo="self"` was not used either: a list longer than the
popover still ends over the page, and the release there closes the popover the same way.

**Tests.** Unit (`RangeSelector.test.ts`): a pick whose release lands on `<body>` after the list
has gone leaves the popover open (fails without the fix); a click outside after such a pick
still closes it (fails when the dropped-click listener outlives its press). Flow 5 presses each
option for 150 ms, as a person does: without the fix it fails in Chromium as well, as in WebKit.
Other `Popover`s in the app hold no overlay component (`ThemeSwitch` has `SelectButton`s), so
the defect is only here.

## Review and fix round

(Filled by the lead.)
