import type { Known } from '../types'

/** What the gate finds on the tracks area's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  // The Subtitles tab's scan button, the picture area's ScanControl: its name does not hold its
  // visible text. Its fix and the removal of this entry are the picture area's.
  {
    screen: 'subtitles',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target:
      'section.editor-tab.tracks-tab[data-tab="subtitles"] button.scan-control__start[data-action="start-scan"]',
  },
]
