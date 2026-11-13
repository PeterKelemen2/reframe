import type { Known } from '../types'

/** What the gate finds on the picture area's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  // crop-manual checks the whole page: the shell's source row and the header's Range button,
  // whose names do not start with their visible text (the shell's and the tracks area's).
  {
    screen: 'crop-manual',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target: 'aside.sources-panel li.sources-panel__node.sources-panel__source',
  },
  {
    screen: 'crop-manual',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target: 'header.workspace__header button.range-selector__trigger[data-field="range"]',
  },
  // The naming editor's variable chips, in the Summary's Output card (the tracks area's).
  {
    screen: 'summary',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target: 'article.rf-card.summary-card[data-card="output"] button.naming-chip[data-variable]',
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
