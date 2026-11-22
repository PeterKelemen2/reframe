function letEscapeLeaveClosedSelect(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || !(event.target instanceof Element)) return
  if (event.target.closest('.p-select') === null) return
  if (event.target.closest('[aria-expanded]')?.getAttribute('aria-expanded') !== 'false') return
  // An own property hides Event.prototype's method, for this event only.
  Object.defineProperty(event, 'stopPropagation', { value: () => {}, configurable: true })
}

const POPUP_MENU_LIST = '.p-menu-overlay .p-menu-list'

/** The element each popup menu's list took the focus from when it opened. */
const menuOpeners = new WeakMap<Element, HTMLElement>()

function menuButton(list: Element): HTMLElement | null {
  const overlayId = list.closest('.p-menu-overlay')?.id
  const controller = overlayId
    ? list.ownerDocument.querySelector<HTMLElement>(`[aria-controls="${CSS.escape(overlayId)}"]`)
    : null
  const button = controller ?? menuOpeners.get(list) ?? null
  return button?.isConnected === true ? button : null
}

function focusFirstMenuItem(event: FocusEvent): void {
  const list = event.target
  if (!(list instanceof Element) || !list.matches(POPUP_MENU_LIST)) return
  const from = event.relatedTarget
  if (from instanceof HTMLElement && !list.contains(from)) menuOpeners.set(list, from)
  if (list.getAttribute('aria-activedescendant')) return
  // The menu's own Home key: the only way in to its focused item.
  list.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', code: 'Home', bubbles: true }))
}

function tabOutOfPopupMenu(event: KeyboardEvent): void {
  if (event.key !== 'Tab' || !(event.target instanceof Element)) return
  if (!event.target.matches(POPUP_MENU_LIST)) return
  // The browser's own Tab then moves on from the button, both ways; the menu closes itself.
  menuButton(event.target)?.focus()
}

/**
 * Keyboard behaviour that PrimeVue's components get wrong for every dialog and menu of the app,
 * fixed once on the document. Returns the function that removes the fixes.
 *
 * - Escape on a closed Select reaches the Dialog or Popover around it: Select stops every
 *   Escape, open or not, so its dialog would not close.
 * - A popup Menu puts its first item in focus when it opens, as a menu button does (WAI-ARIA
 *   APG): PrimeVue focuses the list with no item in focus.
 * - Tab and Shift+Tab in a popup Menu close it and go to the element after or before its menu
 *   button (APG). PrimeVue closes it and leaves the focus where its list was, at the page's end.
 */
export function installKeyboardFixes(doc: Document = document): () => void {
  doc.addEventListener('keydown', letEscapeLeaveClosedSelect, true)
  doc.addEventListener('keydown', tabOutOfPopupMenu, true)
  doc.addEventListener('focusin', focusFirstMenuItem)
  return () => {
    doc.removeEventListener('keydown', letEscapeLeaveClosedSelect, true)
    doc.removeEventListener('keydown', tabOutOfPopupMenu, true)
    doc.removeEventListener('focusin', focusFirstMenuItem)
  }
}
