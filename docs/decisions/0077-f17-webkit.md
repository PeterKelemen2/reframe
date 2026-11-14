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

**B — the gate measured too early (gate fixed, not the app).** WebKit scrolls a newly focused
element into view at its next rendering update, not during the Tab. Measured in headless WebKit
on the Tags tab (a `focusin` listener reading the field's top and `.editor-tabs__panels`'
`scrollTop`): in the event, a microtask, a `setTimeout(0)` and the first frame callback the
field is still at 770 px in a 720 px window (scrollTop 249); in the second frame callback it is
at 639 px (scrollTop 380), with no frames between (a jump, not a smooth scroll). Chromium and
Firefox scroll inside the Tab. The walk called `walkStep` (and `obscured`) right after the key
press, so a field below the fold was still outside the window; `obscured` returns true for a
stop outside it. Once scrolled, nothing covers the field (`elementsFromPoint` at its centre: the
input first); the user sees it in view from the frame after the Tab. Fix: `gate.ts` waits for one
rendering update (two frame callbacks) after each Tab before it judges the stop. The same wait
cleared the naming overrides on `summary` and `group`. A test for the gate (a stop that comes
into view one frame after its focus is not hidden; one that comes 500 ms later is) needs
`gate-checks.spec.ts`, which W2 does not own: the diff went to the lead.

**C — the pointer took the language picker's active option (app fixed).** WebKit sends a
`mousemove` (and `pointermove`) at the pointer's unchanged place when the content under it
changes: when the picker's list appears, when the search filters it, when it scrolls. Logged in
headless WebKit: after typing `fren`, a trusted `mousemove` at the same client point
(662, 387), movement 0, over `fr-CA`; after the reopen, one over `fil`. The test's pointer was
left over the dialog by its earlier click, and the option's `@mousemove` made the option under
it active, so Enter chose it (`fj` in the first run, `fil`/`fr-CA` in later ones). A WebKit user
whose mouse rests over the list gets the same. `LanguagePicker.vue` now takes the active option
from a `mousemove` only when the pointer's client point differs from the previous one seen since
the picker opened (the first one only records it); a click still chooses at once. Unit test:
"keeps the active option of the keys under a pointer that does not move, follows one that does".

**A — the gate's pictures in CSS pixels (gate fixed, found by W1).** `Desktop Safari` has
`deviceScaleFactor` 2 (Chromium and Firefox 1). With `scale: 'css'` WebKit gives a picture in
which the thumbnail's rounded 2 px ring, on a fractional CSS pixel (top 463.31), is blended into
the rows next to it: one full row and two `166,162,242` half rows, 195 of 218 px at 3:1. In the
device-scale picture it is a solid 4-device-px band. The ring is complete on screen. Checked on
a page made for it: a rounded 1 px black ring on a half CSS pixel at device scale factor 2 is two
crisp device rows; WebKit's CSS-scale picture paints it as two `59` rows (68 of 197 px at 3:1);
Chromium's CSS-scale picture and Firefox's draw it crisp, unless the ring is square-cornered
(then WebKit draws it crisp too). Fix: `gate.ts` takes the pictures with `scale: 'device'`;
`comparePixels` walks the device pixels (its scale is the picture's width over the clip's) and
needs `2 × (width + height) × scale²` of them: a 1 CSS px line round the visible part. At scale 1
the walk and the count are the ones before. Only `comparePixels` reads pictures; `obscured`, the
motion check and the computed-colour checks use CSS coordinates from the DOM, not pictures, so
the device scale does not reach them (W1 also saw `toast` fail on `obscured` at scale factor 1:
cause B, above, is not the ratio). Test for the gate (with the one for B, in
`gate-checks.spec.ts`, a file W2 does not own: the diff went to the lead).

No known-list entry.

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

### Fix round — FA (review R1 findings 1–4 and 6)

**1, 2, 6 — a still pointer moves the active option of every list (app fixed, one filter).**
Cause C (W2) is not only the language picker's. PrimeVue's `Select` and `Listbox` (and
`AutoComplete`, `ContextMenu`) move their focused option to the one under the pointer on
`mousemove` (`focusOnHover`, on by default); they do not listen to `pointermove`. So WebKit's
move at a still pointer pulls the keys' option back. Reproduced in headless WebKit with the
review's probe (`select-still`, a file with 24 chapters, the pointer resting on the Range *From*
list, 10 ArrowDown 60 ms apart, a pause of 500 ms, 3 ArrowDown 300 ms apart, Enter): WebKit chose
chapter 12 or 13, the keys 16 (DY 24, 8, 16); Chromium 16. The frame rate `Select` of
`multitrack.mkv` gives the same in WebKit: 48, the keys 72.

Fix: `components/base/stillPointer.ts`, `installStillPointerFilter()`, called in `main.ts` with
the other app-wide fixes (`components/base` has no install point of its own). A window capture
`mousemove` listener stops (`stopImmediatePropagation`) a move at the same client point as the
move before it, unless a button is down. It is installed before the app mounts, so no listener
of the app or of PrimeVue sees the move. What it leaves alone:
- `:hover` (the browser sets it before the event), `mouseover`/`mouseenter`, pointer events and
  presses and clicks. `pointermove` is not filtered: the crop handles drag on it with pointer
  capture, and the frame viewer follows the pointer on it.
- The first move after the page loads (there is no point before it). Checked in headless WebKit
  on a list that a script scrolls three times, 300 ms apart: no move before any mouse event;
  after a real move to 100,100, one move at 100,100 per scroll (`buttons` 0); none while a
  button is held. Chromium and Firefox send none in the three cases.
- A real move: another point passes at once, also the first move after a list opens.
- A drag: a move with a button down always passes. PrimeVue's `Slider` and `Dialog` drag on
  document `mousemove`. Headless WebKit, Chromium and Firefox, the quality slider: pressed,
  +15 px, held still 400 ms, +30 px, released: 22 → 29.7 → 29.7 → 37.7 in all three.
- Touch and pen: their compatibility `mousemove` is filtered like a mouse's (a second tap at
  the same point gets none); their `mousedown`, `mouseup` and `click` go on, and PrimeVue
  chooses on `mousedown` (the review's `range-touch` still picks chapter 6).
- A real move of less than one CSS pixel is stopped (`clientX`/`clientY` are whole numbers):
  the pointer is still over the same element.

After the fix, WebKit still sends its moves (a `pointermove` at 587,406, movement 0,0, over
options 11–14 after the pauses), and the focused option stays with the keys: `select-still`
gives 16 at DY 24, 8 and 16 in WebKit and Chromium; `lang-stale` gives `sq` after 12 ArrowDown
and `ale` after the 13th in both (before: `akk`, then `sq`, in WebKit). A wheel scroll under a
still pointer leaves the active option where it was in WebKit, as Chromium does (`lang-hover`).

The language picker's own fix (`pointerAt`, `onOptionMove`) is removed; its options take
`@mousemove` again. The filter covers both gaps of that fix: a move over the dialog's padding
records the point (`lang-stale`), and the first real move onto an option takes it.

**3 — a press whose release never comes (app fixed).** `pressInList` arms only for
`button === 0`, and adds a window capture `mousedown` listener (once) that removes a release
listener still armed: the next press disarms it. `pointerup`/`pointercancel` was not used: no
`pointercancel` comes when another window or a context menu takes the release. The two guards
overlap: the next press removes the listener of a right press too, so no test fails with the
button check alone removed (table below). Probe `range-lost-release` (a right press on a chapter,
Escape, a click on *100 %* outside the popover): the first click reaches *100 %* and closes the
popover in WebKit and Chromium (before: eaten, the second click did it).

**4 — tests with whole sequences.** `RangeSelector.test.ts`: a click outside after a pick (a
press, the release on `<body>` after the list has gone, its click), then a person's click on a
button outside a task later: the button gets it and the popover closes; the same after a press
in a list with no click (its scrollbar: `mousedown` + `mouseup` only); the same after a right
press and after a main press whose release the page never got.

**Tests.** `stillPointer.test.ts` (4): the first move passes, a move at the same point is
stopped before the element, the document and a later window capture listener, a move elsewhere
passes at once; every move of a drag passes; only `mousemove` is stopped (`pointermove`,
`mouseover`, a tap's press, release and click go on); the filter can be removed.
`LanguagePicker.test.ts` installs the filter as `main.ts` does; its pointer test covers the moves
at a still point when the list opens, filters and empties beside the pointer, and the first move
after a reopen. `e2e/still-pointer.spec.ts` (new): the frame rate `Select` (21 options, it
scrolls) and the language picker, the pointer resting on or beside the list, with a person's
pauses; both fail in WebKit without the filter (`Expected "72", Received "48"`;
`Expected "sq", Received "akk"`) and pass in all three browsers with it. Runs with the fix:
`still-pointer.spec.ts`, flows 1–5 and `a11y/keyboard-*.spec.ts` in Chromium, Firefox and
WebKit, 48 passed (2.3 min); then the whole suite in the three, 309 passed (14.2 min). Unit
2157 passed; lint, format and types clean.

**Mutations** (each test function failed at least once; the code restored after each):

| Mutation | Fails |
|---|---|
| filter stops nothing | `stillPointer` first-move, drag, only-mousemove; `LanguagePicker` pointer test |
| a drag's still move stopped too | `stillPointer` drag |
| only `clientX` compared | `stillPointer` first-move |
| the first move stopped | `stillPointer` first-move, drag, only-mousemove |
| `stopPropagation` instead of `stopImmediatePropagation` | `stillPointer` first-move |
| `pointermove` filtered too | `stillPointer` only-mousemove |
| the last point kept from the first move | `stillPointer` first-move, drag; `LanguagePicker` pointer test |
| the filter not installed in the picker test | `LanguagePicker` pointer test (`hu` → `de`) |
| the picker's old local fix, with the filter | `LanguagePicker` pointer test (the first real move onto an option ignored: `egy`, not `de`) |
| the picker's old local fix, no filter | `LanguagePicker` pointer test (`lang-stale`: `egy` → `de`) |
| `main.ts` without the filter (e2e, WebKit) | both `still-pointer.spec.ts` tests |
| the original `pressInList` | right press, main press with no release |
| no `setTimeout` removal of the click drop | press with no click (scrollbar) |
| no disarm on the next press | main press with no release |
| no button check | none: the disarm covers it |
| no button check and no disarm | right press, main press with no release |
| the release listener not `once`, no disarm | click outside after a pick (and the next three) |

**Seen, not changed (PrimeVue).** `Popover` sets its `selfClick` on any `mousedown` in its
content and clears it on the next click. A press in the popover that has no click (a right press
on its title with a chapter list open, then Escape) makes the next click outside leave the
popover open; that click still reaches its target (probe `range-lost-release` with
`WHERE=title`, WebKit and Chromium; `pressInList` is not involved). PrimeVue's `Select` also
chooses an option on a press of any button (a right press on a chapter chooses it).

No known-list entry.
