import type { Known } from '../types'

/** What the gate finds on the tracks area's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  // Names that do not start with the visible text: a matrix cell, the variable chips, and the
  // Subtitles tab's scan button (the picture area's ScanControl).
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
  {
    screen: 'subtitles',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target:
      'section.editor-tab.tracks-tab[data-tab="subtitles"] button.scan-control__start[data-action="start-scan"]',
  },
]
