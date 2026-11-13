/** Where the keyboard focus goes when the element that had it is removed or disabled. */

/** The focus is on no control: its element went away, and the browser gave it to the page. */
export function focusLost(): boolean {
  const active = document.activeElement
  return active === null || active === document.body
}

/** Focuses the workspace's selected editor tab, else *Open files…*; `false` when neither shows. */
export function focusWorkspace(): boolean {
  const target =
    document.querySelector<HTMLElement>('.editor-tabs [role="tab"][aria-selected="true"]') ??
    document.querySelector<HTMLElement>('.workspace__open')
  target?.focus()
  return target !== null
}

const FOCUSABLE = [
  'button:not(:disabled)',
  'a[href]',
  'input:not(:disabled)',
  'select:not(:disabled)',
  'textarea:not(:disabled)',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

/**
 * Focuses the first control inside a popover that has just opened, else the panel itself.
 * PrimeVue's popover opens at the end of the page and keeps a focus that is inside it there, but
 * it does not take the focus from its trigger.
 */
export function focusFirstIn(panel: HTMLElement | null): void {
  if (panel === null) return
  const first = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].find(
    (element) => !element.closest('[aria-hidden="true"]'),
  )
  if (first !== undefined) {
    first.focus()
    return
  }
  // In the Tab order: the popover's focus trap sends Tab round to it, and without a stop
  // inside, Tab would rest on the trap's invisible guard, where Escape loses the focus.
  panel.tabIndex = 0
  panel.focus()
}
