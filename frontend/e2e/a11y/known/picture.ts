import type { Known } from '../types'

/** What the gate finds on the picture area's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  // crop-manual checks the whole page: the shell's source row, whose name does not start with
  // its visible text.
  {
    screen: 'crop-manual',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target: 'aside.sources-panel li.sources-panel__node.sources-panel__source',
  },
  // In dark, on a changed option's tinted row, the focus of its buttons is 1.23:1.
  {
    screen: 'video-advanced',
    check: 'focus',
    theme: 'dark',
    rule: 'indicator-contrast',
    target:
      'div.rf-field[data-path="video.advanced.aq-mode"] button.advanced-reset[data-action="reset"]',
  },
  {
    screen: 'video-advanced',
    check: 'focus',
    theme: 'dark',
    rule: 'indicator-contrast',
    target: 'div.rf-field[data-path="video.advanced.aq-mode"] button.rf-field__help',
  },
]
