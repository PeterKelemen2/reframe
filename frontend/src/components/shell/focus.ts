/** Where the keyboard focus goes when the element that had it is removed or disabled. */

import { nextTick } from 'vue'
import type { Router } from 'vue-router'

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

/** Focuses the heading of the view on screen (not the workspace); `false` when none shows. */
export function focusView(): boolean {
  const heading = document.querySelector<HTMLElement>('main[data-view] h1')
  if (heading === null) return false
  heading.tabIndex = -1
  heading.focus()
  return true
}

/**
 * After each move to another view, a focus that went away with the old view goes to the new
 * one: the workspace's editor or *Open files…*, another view's heading. The first view of a page
 * load takes no focus. Returns the function that removes it.
 */
export function refocusAfterNavigation(router: Router): () => void {
  return router.afterEach(async (to, from, failure) => {
    if (failure !== undefined || from.matched.length === 0) return
    await nextTick()
    if (!focusLost()) return
    if (to.name === 'workspace') focusWorkspace()
    else focusView()
  })
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
