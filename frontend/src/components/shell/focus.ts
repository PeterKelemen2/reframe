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
