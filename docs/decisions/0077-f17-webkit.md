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

(Filled by W1.)

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
