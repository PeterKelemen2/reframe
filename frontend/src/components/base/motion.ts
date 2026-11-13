type ScrollOptions = ScrollIntoViewOptions | ScrollToOptions

function instant<T>(options: T): T {
  return typeof options === 'object' && options !== null && 'behavior' in options
    ? { ...options, behavior: 'auto' }
    : options
}

/**
 * Makes every scroll that code asks to be smooth (PrimeVue's Listbox scrolls its options into
 * view so) jump instead while the user asks for reduced motion: the browsers scroll smoothly
 * on request whatever the setting. Returns the function that removes it.
 */
export function installReducedMotionScrolling(
  view: Pick<Window, 'matchMedia'> & { Element: typeof Element } = window,
): () => void {
  const reduced = view.matchMedia?.('(prefers-reduced-motion: reduce)')
  if (reduced === undefined) return () => {}
  const element = view.Element.prototype
  const originals = {
    scrollIntoView: element.scrollIntoView,
    scroll: element.scroll,
    scrollTo: element.scrollTo,
    scrollBy: element.scrollBy,
  }
  element.scrollIntoView = function (this: Element, options?: boolean | ScrollIntoViewOptions) {
    originals.scrollIntoView.call(this, reduced.matches ? instant(options) : options)
  }
  for (const name of ['scroll', 'scrollTo', 'scrollBy'] as const) {
    const original = originals[name] as (this: Element, ...args: unknown[]) => void
    element[name] = function (this: Element, ...args: unknown[]) {
      const [first, ...rest] = args
      original.call(this, reduced.matches ? instant(first as ScrollOptions) : first, ...rest)
    } as Element[typeof name]
  }
  return () => Object.assign(element, originals)
}
