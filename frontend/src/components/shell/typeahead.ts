/** Keys typed further apart than this start a new search. */
const PAUSE_MS = 500

/**
 * The type-ahead of a listbox or tree: a printable key moves to the next item whose name starts
 * with the keys typed in quick succession. Typing one letter again goes on to the next item
 * that starts with it. The widget handles Space before: it selects there.
 */
export function createTypeahead(): (
  event: KeyboardEvent,
  names: readonly string[],
  current: number,
) => number | null {
  let typed = ''
  let last = 0
  return (event, names, current) => {
    if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return null
    const now = Date.now()
    typed = now - last > PAUSE_MS ? event.key : typed + event.key
    last = now
    const wanted = typed.toLocaleLowerCase()
    const repeated = [...wanted].every((char) => char === wanted[0])
    const prefix = repeated ? (wanted[0] ?? '') : wanted
    // A new search, or one letter again, starts after the current item; a longer one at it.
    const start = repeated ? current + 1 : current
    for (let step = 0; step < names.length; step++) {
      const index = (((start + step) % names.length) + names.length) % names.length
      if (names[index]?.toLocaleLowerCase().startsWith(prefix)) return index
    }
    return null
  }
}
