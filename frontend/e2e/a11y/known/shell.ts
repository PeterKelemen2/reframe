import type { Known } from '../types'

/** What the gate finds on the shell's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  // Not a fault of the page: the selected preset's fill is see-through (16 % of the primary
  // colour), and the probe's `rgba()` divides canvas pixels by their alpha a second time, so it
  // takes the fill for a light colour (r 814). The ring is 5.4:1 against the real fill in dark.
  {
    screen: 'presets',
    check: 'focus',
    theme: 'dark',
    rule: 'indicator-contrast',
    target: 'main.view.presets-view[data-view="presets"] li.preset-tree__preset[data-preset]',
  },
  // The header's Range button's name does not start with its visible text (the tracks area's
  // component).
  {
    screen: 'toast',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target: 'header.workspace__header button.range-selector__trigger[data-field="range"]',
  },
]
