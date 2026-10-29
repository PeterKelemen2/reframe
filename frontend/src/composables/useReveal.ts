import { nextTick, type MaybeRefOrGetter, type Ref, toValue, watch } from 'vue'

import { useUiStore } from '@/stores/ui'

/** CSS class that a revealed element gets for a moment (the design system styles it). */
export const REVEALED_CLASS = 'is-revealed'
const REVEALED_MS = 1500
/** A tab loads its component on first use, so its targets mount after the request. */
const REQUEST_TTL_MS = 3000
const FOCUSABLE = 'input, select, textarea, button, [tabindex]:not([tabindex="-1"])'

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
      node.scrollIntoView({ block: 'center', behavior: 'smooth' })
      const focusable = node.matches(FOCUSABLE) ? node : node.querySelector<HTMLElement>(FOCUSABLE)
      focusable?.focus({ preventScroll: true })
      node.classList.add(REVEALED_CLASS)
      setTimeout(() => node.classList.remove(REVEALED_CLASS), REVEALED_MS)
    },
    { immediate: true },
  )
}
