/**
 * Keyboard behaviour that PrimeVue's components get wrong for every dialog and menu of the app,
 * fixed once on the document. Returns the function that removes the fixes.
 *
 * - Escape on a closed Select reaches the Dialog or Popover around it: Select stops every
 *   Escape, open or not, so its dialog would not close.
 * - A popup Menu puts its first item in focus when it opens, as a menu button does (WAI-ARIA
 *   APG): PrimeVue focuses the list with no item in focus.
 */
export function installKeyboardFixes(doc: Document = document): () => void {
  const onKeydown = (event: KeyboardEvent): void => {
    if (event.key !== 'Escape' || !(event.target instanceof Element)) return
    if (event.target.closest('.p-select') === null) return
    if (event.target.closest('[aria-expanded]')?.getAttribute('aria-expanded') !== 'false') return
    // An own property hides Event.prototype's method, for this event only.
    Object.defineProperty(event, 'stopPropagation', { value: () => {}, configurable: true })
  }
  const onFocusin = (event: FocusEvent): void => {
    const list = event.target
    if (!(list instanceof Element) || !list.matches('.p-menu-overlay .p-menu-list')) return
    if (list.getAttribute('aria-activedescendant')) return
    // The menu's own Home key: the only way in to its focused item.
    list.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', code: 'Home', bubbles: true }))
  }
  doc.addEventListener('keydown', onKeydown, true)
  doc.addEventListener('focusin', onFocusin)
  return () => {
    doc.removeEventListener('keydown', onKeydown, true)
    doc.removeEventListener('focusin', onFocusin)
  }
}
