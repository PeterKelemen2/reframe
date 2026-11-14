import type { Known } from '../types'

// Firefox makes a box that scrolls a Tab stop of its own. Its ring (2 px, 2 px outside) is cut
// away by the clipping ancestor around it; only the top edge, or nothing, can be seen.
const TAB_LIST = 'div.editor-tabs div.p-tablist-content.p-tablist-viewport' // `.p-tablist` clips
const PREVIEW = 'aside.preview-panel div.preview-panel__content' // `.preview-panel` clips

/** What the gate finds on the picture area's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  ...['crop-manual', 'preview-frames', 'split-compare'].map((screen): Known => ({
    screen,
    check: 'focus',
    browser: 'firefox',
    rule: 'indicator-contrast',
    target: PREVIEW,
  })),
  {
    screen: 'crop-manual',
    check: 'focus',
    browser: 'firefox',
    rule: 'indicator-contrast',
    target: TAB_LIST,
  },
  // The slate ring against the magnifier's grey surface: 2.88:1, in light.
  {
    screen: 'crop-manual',
    check: 'focus',
    theme: 'light',
    rule: 'indicator-contrast',
    target: 'section.crop-magnifier button.crop-magnifier__step[data-action="frame-previous"]',
  },
  // The open command drawer covers the bottom of the Video tab: a control partly under it keeps
  // less than 24 px (2.5.8). Which control that is differs by browser (and theme), as measured.
  {
    screen: 'command-drawer',
    check: 'axe',
    browser: 'chromium',
    rule: 'target-size',
    target: 'div.rf-field[data-path="video.framerate_mode"] button.rf-field__help',
  },
  {
    screen: 'command-drawer',
    check: 'axe',
    browser: 'firefox',
    theme: 'dark',
    rule: 'target-size',
    target:
      'div.rf-field[data-path="video.rate_control.value"] input.p-inputtext.p-inputnumber-input',
  },
  {
    screen: 'command-drawer',
    check: 'axe',
    browser: 'firefox',
    rule: 'target-size',
    target: 'div.rf-field[data-path="video.rate_control.value"] span.p-slider-handle',
  },
]
