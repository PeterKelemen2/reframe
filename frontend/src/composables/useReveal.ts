import { nextTick, type MaybeRefOrGetter, type Ref, toValue, watch } from 'vue'

import { useUiStore } from '@/stores/ui'

/** CSS class that a revealed element gets for a moment (the design system styles it). */
export const REVEALED_CLASS = 'is-revealed'
/** The class goes when its animation ends; without motion (no animation), after this. */
const REVEALED_MS = 2400
const ANIMATION = 'rf-reveal'
/** A tab loads its component on first use, so its targets mount after the request. */
const REQUEST_TTL_MS = 3000
const FOCUSABLE = 'input, select, textarea, button, [tabindex]:not([tabindex="-1"])'
const PRESSED = '[aria-pressed="true"], [aria-checked="true"]'

/** The end of each element's running highlight. */
const running = new WeakMap<HTMLElement, () => void>()

/** Gives `node` the class for one run of its animation; a second reveal starts it again. */
function highlight(node: HTMLElement): void {
  running.get(node)?.()
  node.classList.remove(REVEALED_CLASS)
  // Reading the layout ends the running animation, so the class's next one starts from 0.
  void node.offsetWidth
  node.classList.add(REVEALED_CLASS)
  const ended = (event: AnimationEvent) => {
    if (event.target === node && event.animationName === ANIMATION) done()
  }
  const timer = setTimeout(done, REVEALED_MS)
  function done(): void {
    clearTimeout(timer)
    node.removeEventListener('animationend', ended)
    node.classList.remove(REVEALED_CLASS)
    running.delete(node)
  }
  node.addEventListener('animationend', ended)
  running.set(node, done)
}

/**
 * Makes `element` the target of `ui.reveal(path)`: when that path is asked for, it scrolls into
 * view, its first focusable descendant takes the focus, and it carries `REVEALED_CLASS` briefly.
 * `path` may change (a track row that moves) or be empty (no target).
 */
export function useReveal(
  path: MaybeRefOrGetter<string | null | undefined>,
  element: Readonly<Ref<HTMLElement | null | undefined>>,
): void {
  const ui = useUiStore()
  watch(
    () => [ui.revealed, toValue(path), element.value] as const,
    async ([request, target, node]) => {
      if (request === null || !target || !node || request.path !== target) return
      if (performance.now() - request.at > REQUEST_TTL_MS) return
      ui.revealDone(request)
      await nextTick()
      const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
      node.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' })
      // A field's label row comes first and may hold its help button: the control is what was
      // asked for. In a group of buttons (a SelectButton), the pressed one is its value.
      const focusable = node.matches(FOCUSABLE)
        ? node
        : (node.querySelector<HTMLElement>(`.rf-field__control :is(${PRESSED})`) ??
          node.querySelector<HTMLElement>(`.rf-field__control :is(${FOCUSABLE})`) ??
          node.querySelector<HTMLElement>(FOCUSABLE))
      focusable?.focus({ preventScroll: true })
      highlight(node)
    },
    { immediate: true },
  )
}
