import type { Known } from '../types'

// Firefox makes a box that scrolls a Tab stop of its own. Its ring (2 px, 2 px outside) is cut
// away by the clipping ancestor around it: `.p-tablist` round the tab list viewport,
// `.preview-panel` round its content (only the top edge is seen).
const CLIPPED_SCROLLERS = [
  'div.editor-tabs div.p-tablist-content.p-tablist-viewport',
  'aside.preview-panel div.preview-panel__content',
]

/** What the gate finds on the tracks area's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = CLIPPED_SCROLLERS.map((target) => ({
  screen: 'group',
  check: 'focus',
  browser: 'firefox',
  rule: 'indicator-contrast',
  target,
}))
