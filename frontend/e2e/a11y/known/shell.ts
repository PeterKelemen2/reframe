import type { Known } from '../types'

// Firefox makes a box that scrolls a Tab stop of its own. Its ring (2 px, 2 px outside) is cut
// away by the clipping ancestor around it; only the top edge, or nothing, can be seen.
const TAB_LIST = 'div.editor-tabs div.p-tablist-content.p-tablist-viewport' // `.p-tablist` clips
const PREVIEW = 'aside.preview-panel div.preview-panel__content' // `.preview-panel` clips

/** What the gate finds on the shell's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  // `main.settings-view` (overflow: clip) cuts the ring of the scrolling body on every side.
  {
    screen: 'settings',
    check: 'focus',
    browser: 'firefox',
    rule: 'indicator-contrast',
    target: 'main.settings-view[data-view="settings"] div.settings-view__body',
  },
  ...['toast', 'status-error'].flatMap((screen): Known[] => [
    { screen, check: 'focus', browser: 'firefox', rule: 'indicator-contrast', target: TAB_LIST },
    { screen, check: 'focus', browser: 'firefox', rule: 'indicator-contrast', target: PREVIEW },
  ]),
]
