# 0076 — F-16: what the i18n and accessibility audit checks, and how

- Status: accepted
- Date: 2026-11-13
- Steps: F-16 (F-17, F-19)

## Context

The whole of [06 §F-16](../plan/06-web-app.md#f-16-i18n-and-accessibility) is one bullet:

> Audit that every string goes through vue-i18n (English first; the rule and its check start in
> F-1). Full keyboard paths. Visible focus. WCAG AA contrast in both themes. Respect
> `prefers-reduced-motion`.

[0043](0043-plan-review-before-m3.md) item 8 moved i18n to F-1 and left the accessibility work
and the final audit to F-16. The frontend (138 components, checked on 2026-11-13) already has:

- vue-i18n for every template string, with two checks in `src/i18n/checks/`. One finds
  literal text in a `<template>`. The other finds message keys that `en` does not have. Keys
  built at run time are not seen.
- `src/styles/contrast.test.ts`: the contrast of PrimeVue's own variables in our preset, in
  both themes.
- In `tokens.css`, `prefers-reduced-motion: reduce` sets PrimeVue's and our transition
  durations to 0.
- A global `:focus-visible` ring in `main.css`.
- Keyboard work in each milestone: shortcuts, the matrix, the crop keys, the Range popover.

Nothing checks the rendered app as a whole. There is no axe or similar tool, no check that
each focused element shows its focus, and no check that animations stop under reduced motion.
Numbers are formatted in two ways: some go through vue-i18n's `n()`, many through `toFixed`,
which always writes a period. Strings built in scripts (toasts, refusals, accessible names set
in code) are seen by no check.

## Decision

1. **What the audit checks.** F-16 is done when each point holds on every screen of the web UI,
   in Chromium and Firefox (headless), in the light and the dark theme:
   1. **Strings.** Every text a user reads or hears goes through vue-i18n:
      - template text and visible attributes (the existing check);
      - strings built in scripts: toasts, refusals, accessible names, `title` and
        `aria-*` set in code;
      - PrimeVue's own strings (`primevueLocale.ts`).

      Numbers, dates and lists are formatted with the app's locale (`n()`, `d()` or `Intl`
      with `locale`), not with `toFixed` or string joins. Text is never built by joining
      translated pieces in a fixed order; one message with placeholders does it, and
      plurals use vue-i18n's plural forms. English is the only locale (`SUPPORTED_LOCALES`).
   2. **Full keyboard paths.**
      - Every action of the UI can be done with the keyboard alone, in a logical tab order.
      - There is no keyboard trap. A modal dialog or popover keeps the focus inside while it
        is open, closes on Escape and gives the focus back to what opened it.
      - Each custom widget follows its WAI-ARIA Authoring Practices pattern (its role, its
        keys).
      - An action that is drag-only today (crop handles, the split-compare divider, a drop of
        files) has a keyboard way.
      - The shortcuts of [03 §App layout](../plan/03-features.md#app-layout) work.
   3. **Visible focus.**
      - Every element that takes the focus from the keyboard shows a focus indicator
        (WCAG 2.2: 2.4.7 Focus Visible, 2.4.11 Focus Not Obscured (Minimum)).
      - The indicator has 3:1 contrast with what is next to it (1.4.11).
   4. **WCAG AA contrast in both themes.**
      - Text: 4.5:1, large text 3:1 (1.4.3).
      - UI parts and graphics that carry meaning: 3:1 (1.4.11). These include borders of
        inputs, states, icons without text and chart marks.
      - Disabled controls are exempt, as WCAG says.
   5. **Reduced motion.** With `prefers-reduced-motion: reduce`, no CSS transition or
      animation runs (no running `document.getAnimations()`, every computed duration 0), and
      nothing scrolls smoothly. Video does not start by itself: it never does in Reframe;
      playing is the user's action.
2. **How: a gate in the end-to-end tests (task G).**
   - A Playwright spec visits a fixed list of screens. Each screen gets an id, set-up steps
     and the area that owns it (the list is in the M10 breakdown, "F-16").
   - On each screen, in both themes, it runs axe-core with the WCAG 2.0/2.1/2.2 A and AA rules.
   - It tabs through the screen and checks that each stop shows a focus indicator.
   - With reduced motion emulated, it checks that nothing animates.
   - A finding that is known and not fixed yet sits in its area's list
     (`e2e/a11y/known/<area>.ts`). The gate fails on a finding that is not listed, and on a
     listed one that no longer happens, so the lists only shrink.
   - At the end of F-16 the lists are empty, except entries this record names with a reason.
3. **The new dependency.** `@axe-core/playwright` (a dev dependency). No tool in the project
   checks the rendered page against WCAG; writing contrast and ARIA rules by hand would copy
   axe badly. The token test stays: it checks every variable, including states that no screen
   shows.
4. **Ports.** `e2e/support/servers.ts` takes its first port from the environment
   (`REFRAME_E2E_PORT`, default 8750), so that agents can run the flows and the gate on ports of
   their own at the same time.
5. **Not in F-16** (each can come later with its own record):
   - **A layout for windows below about 1100×700 logical pixels.** `docs/status.md` "Not
     verified" left it to "F-16 or a later step". The plan's F-16 asks for AA contrast, not
     the whole of WCAG AA. Reflow (1.4.10) and text resize (1.4.4) are not checked. This is
     a question for the owner; the default is "later".
   - **Server messages.** The texts of validation issues, fixes and errors come from the
     server in English. They are data, shown as they are: translating them is a server
     change for a second locale.
   - **WebKit** (Safari, WebKitGTK of the Linux desktop) is F-17's.
   - **Screen readers.** A real test with Orca or NVDA is recorded as not verified. The audit
     checks the roles, names and states that axe and the keyboard walk can see.
   - **The native dialogs and the tray menu of the desktop app.** They belong to the
     operating system.

## Consequences

- The gate adds a few minutes to `npm run e2e`. It is the record of what F-16 checked: each
  screen, each theme, each check.
- Each component area fixes its own findings, so the agents never edit the same file
  ([m10-breakdown.md](../m10-breakdown.md) "F-16").

## Task G: the gate and the shared layer

(Filled in after the task.)

## Task K1: the shell and the pages

(Filled in after the task.)

## Task K2: the picture and the video

(Filled in after the task.)

## Task K3: the tracks and the batch

(Filled in after the task.)

## Review and fix round

(Filled in after the reviews.)
