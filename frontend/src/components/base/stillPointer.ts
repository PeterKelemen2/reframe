/**
 * Stops a `mousemove` at the client point of the move before it, before any listener of the
 * page sees it; a move with a button down (a drag) always goes on. WebKit sends one when the
 * content under a still pointer changes (a list opens, filters or scrolls), and a list that
 * moves its active option to the one under the pointer (PrimeVue's, the language picker) would
 * take it from the arrow keys: Enter would choose the option under the pointer. `:hover` does
 * not come from the event. Returns the function that removes the filter.
 */
export function installStillPointerFilter(view: Window = window): () => void {
  let last: { x: number; y: number } | null = null
  const filter = (event: MouseEvent) => {
    const still = event.clientX === last?.x && event.clientY === last.y
    last = { x: event.clientX, y: event.clientY }
    if (still && event.buttons === 0) event.stopImmediatePropagation()
  }
  view.addEventListener('mousemove', filter, true)
  return () => view.removeEventListener('mousemove', filter, true)
}
