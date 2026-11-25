import { useEventListener } from '@vueuse/core'
import { ref, type Ref } from 'vue'

import type { FrameLink } from '@/api/types'
import type { Zoom } from '@/stores/preview'

/** The width of a picture box: the container's width at `fit` (no taller than the screen allows). */
export function boxWidth(
  frame: Pick<FrameLink, 'width' | 'height'>,
  zoom: Zoom,
  pictures = 1,
): string {
  if (zoom === 'fit')
    return pictures === 1 ? `min(100%, ${(60 * frame.width) / frame.height}vh)` : '100%'
  return `${frame.width * zoom * pictures}px`
}

// A space types in these; a range input ignores it.
const TAKES_SPACE = 'input:not([type="range"]), select, textarea, [contenteditable]'

/**
 * While Space is held, a drag on `stage` scrolls it, as a scrollbar would. Only a stage with
 * something to scroll takes the key, so Space keeps its other meanings elsewhere.
 */
export function usePanOnSpace(stage: Readonly<Ref<HTMLElement | null>>) {
  /** Space is held and the stage can scroll: a drag pans. */
  const ready = ref(false)
  const dragging = ref(false)
  let hovered = false
  let drag: { id: number; x: number; y: number; left: number; top: number } | null = null

  function end(): void {
    drag = null
    dragging.value = false
    ready.value = false
  }

  function takes(event: KeyboardEvent): boolean {
    const element = stage.value
    if (element === null || event.code !== 'Space') return false
    if (event.ctrlKey || event.metaKey || event.altKey) return false
    const target = event.target instanceof Element ? event.target : null
    if (target?.closest(TAKES_SPACE)) return false
    if (!hovered && !(target !== null && element.contains(target))) return false
    return element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight
  }

  useEventListener(window, 'keydown', (event: KeyboardEvent) => {
    if (!takes(event)) return
    event.preventDefault()
    ready.value = true
  })
  useEventListener(window, 'keyup', (event: KeyboardEvent) => {
    if (event.code !== 'Space') return
    // A button that has the focus is pressed on the key's release.
    if (ready.value) event.preventDefault()
    end()
  })
  useEventListener(window, 'blur', end)
  useEventListener(stage, 'pointerenter', () => {
    hovered = true
  })
  useEventListener(stage, 'pointerleave', () => {
    hovered = false
  })
  // Before the picture's own handlers (the crop handles, the split slider) see the press.
  useEventListener(
    stage,
    'pointerdown',
    (event: PointerEvent) => {
      const element = stage.value
      if (!ready.value || element === null || event.button !== 0) return
      event.preventDefault()
      event.stopPropagation()
      drag = {
        id: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        left: element.scrollLeft,
        top: element.scrollTop,
      }
      dragging.value = true
      element.setPointerCapture?.(event.pointerId)
    },
    { capture: true },
  )
  useEventListener(stage, 'pointermove', (event: PointerEvent) => {
    const element = stage.value
    if (drag === null || element === null || event.pointerId !== drag.id) return
    element.scrollLeft = drag.left - (event.clientX - drag.x)
    element.scrollTop = drag.top - (event.clientY - drag.y)
  })
  const release = (event: PointerEvent): void => {
    if (drag !== null && event.pointerId === drag.id) {
      drag = null
      dragging.value = false
    }
  }
  useEventListener(stage, 'pointerup', release)
  useEventListener(stage, 'pointercancel', release)

  return { ready, dragging }
}
