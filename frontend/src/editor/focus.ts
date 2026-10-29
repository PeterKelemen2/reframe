const NOT_TEXT_INPUTS = new Set([
  'button',
  'checkbox',
  'color',
  'file',
  'image',
  'radio',
  'range',
  'reset',
  'submit',
])

/** A field that takes typing: a text-like `input`, a `textarea` or a `contenteditable`. */
export function isTextField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target instanceof HTMLTextAreaElement) return true
  if (target.closest('[contenteditable]:not([contenteditable="false"])') !== null) return true
  return target instanceof HTMLInputElement && !NOT_TEXT_INPUTS.has(target.type)
}

/**
 * Puts what was typed into the focused field into the job, and gives the focus back to the
 * field. Some fields write only when they lose the focus (PrimeVue's `InputNumber`, the naming
 * editor's), so a shortcut pressed inside one would otherwise act on the job without it.
 */
export function commitFocusedField(): void {
  const focused = document.activeElement
  if (!(focused instanceof HTMLElement) || !isTextField(focused)) return
  focused.blur()
  if (focused.isConnected) focused.focus({ preventScroll: true })
}
