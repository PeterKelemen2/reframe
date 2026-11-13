import type { Known } from '../types'

/** What the gate finds on the tracks area's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  // Names that do not start with the visible text: a matrix cell and the variable chips.
  {
    screen: 'matrix',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target: 'div.matrix-dialog button.matrix__cell[data-cell="subtitle:0"]',
  },
  {
    screen: 'naming-editor',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target: 'article.rf-card.summary-card[data-card="output"] button.naming-chip[data-variable]',
  },
]
