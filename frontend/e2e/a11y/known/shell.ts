import type { Known } from '../types'

/** What the gate finds on the shell's screens and is not fixed yet; the list only shrinks. */
export const known: Known[] = [
  // The preset list (PrimeVue Listbox) takes the focus with no option in focus: nothing shows
  // where the focus is. Firefox also stops on the Listbox's hidden first and last elements.
  {
    screen: 'preset-picker',
    check: 'focus',
    rule: 'no-indicator',
    target: 'div.preset-picker__popover ul.p-listbox-list',
  },
  {
    screen: 'preset-picker',
    check: 'focus',
    browser: 'firefox',
    rule: 'no-indicator',
    target: 'div.preset-picker__popover span[role="presentation"]',
  },
  {
    screen: 'preset-picker',
    check: 'focus',
    browser: 'firefox',
    rule: 'obscured',
    target: 'div.preset-picker__popover span[role="presentation"]',
  },
  // A category row's name is not its visible text.
  {
    screen: 'presets',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target: 'main.view.presets-view[data-view="presets"] li.preset-tree__category',
  },
  // In dark, a preset row's focus is 1.1:1 against its unfocused look.
  {
    screen: 'presets',
    check: 'focus',
    theme: 'dark',
    rule: 'indicator-contrast',
    target: 'main.view.presets-view[data-view="presets"] li.preset-tree__preset[data-preset]',
  },
  // The row actions of the queue table are covered where the focus lands on them.
  ...['', '[data-action="cancel"]', '[data-action="duplicate"]', '[data-action="edit"]']
    .concat(['[data-action="log"]', '[data-action="remove"]'])
    .map((action): Known => ({
      screen: 'queue',
      check: 'focus',
      rule: 'obscured',
      target: `main.queue-view[data-view="queue"] button.p-button.p-button-icon-only${action}`,
    })),
  {
    screen: 'queue',
    check: 'focus',
    browser: 'chromium',
    rule: 'obscured',
    target:
      'main.queue-view[data-view="queue"] button.p-button.p-button-icon-only[data-action="retry"]',
  },
  // A read-only path is painted in the disabled colours, 4.07:1 in dark; it is not disabled.
  {
    screen: 'settings-tools',
    check: 'axe',
    theme: 'dark',
    rule: 'color-contrast',
    target: '#settings-tools input.p-inputtext.p-inputtext-fluid[data-field="override"]',
  },
  // A source's name does not start with its visible text.
  {
    screen: 'toast',
    check: 'axe',
    rule: 'label-content-name-mismatch',
    target: 'aside.sources-panel li.sources-panel__node.sources-panel__source',
  },
]
