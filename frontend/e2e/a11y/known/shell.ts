import type { Known } from '../types'

/** What the gate finds on the shell's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  // In dark, a preset row's focus is 1.1:1 against its unfocused look.
  {
    screen: 'presets',
    check: 'focus',
    theme: 'dark',
    rule: 'indicator-contrast',
    target: 'main.view.presets-view[data-view="presets"] li.preset-tree__preset[data-preset]',
  },
]
