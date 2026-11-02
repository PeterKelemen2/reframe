import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import type { FrameLink } from '@/api/types'
import { notBuilt } from '@/notBuilt'

/** What the preview panel shows of the current frame. */
export type ViewMode = 'source' | 'output' | 'split' | 'side'

/** `fit` the panel, or 1 (100 %) or 2 (200 %) CSS pixels per source pixel. */
export type Zoom = 'fit' | 1 | 2

/** A point of the source picture as FFmpeg decodes it, in pixels from its top-left corner. */
export interface SourcePoint {
  x: number
  y: number
}

/**
 * The preview panel's frames: the strip of the shown file, the current frame, the output frame
 * of the editor's job, the view mode, the zoom and the pointer over the picture.
 */
export const usePreviewStore = defineStore('preview', () => {
  /** The file the frames are of: the editor's shown file; `null` when none is shown. */
  const sourceId = computed<string | null>(() => null)
  /** Evenly spaced source frames (Settings → Preview's count), in timestamp order. */
  const strip = shallowRef<FrameLink[]>([])
  /** The answer's notes (how an HDR picture was mapped for display, frames left out). */
  const notes = ref<string[]>([])
  const loading = ref(false)
  /** Why the strip could not be made (the problem's title). */
  const error = ref<string | null>(null)
  /** The strip frame shown; `null` when a seek shows a frame between them. */
  const index = ref<number | null>(null)
  /** The source frame shown: a strip frame, or the frame of the last seek. */
  const current = computed<FrameLink | null>(() => null)
  /**
   * The output frame of the editor's job at `current`'s time (`preview/render`), while the panel
   * shows a view mode that needs it; `null` while it is on its way or out of date.
   */
  const output = shallowRef<FrameLink | null>(null)
  const rendering = ref(false)
  const renderError = ref<string | null>(null)
  const viewMode = ref<ViewMode>('source')
  const zoom = ref<Zoom>('fit')
  /** The pointer over the shown source picture; `null` when it is elsewhere. */
  const pointer = ref<SourcePoint | null>(null)

  /* oxlint-disable unicorn/consistent-function-scoping -- the stubs until task A builds them */
  /** Shows strip frame `at`. */
  function select(at: number): void {
    notBuilt('preview.select', at)
  }

  /** The next (1) or previous (-1) strip frame. */
  function step(delta: 1 | -1): void {
    notBuilt('preview.step', delta)
  }

  /** Shows the source frame at `seconds` (`preview/frames` with that timestamp). */
  async function seek(seconds: number): Promise<void> {
    notBuilt('preview.seek', seconds)
  }

  /** Asks for the strip again (its URLs have expired, or it failed). */
  async function reload(): Promise<void> {
    notBuilt('preview.reload')
  }
  /* oxlint-enable unicorn/consistent-function-scoping */

  return {
    sourceId,
    strip,
    notes,
    loading,
    error,
    index,
    current,
    output,
    rendering,
    renderError,
    viewMode,
    zoom,
    pointer,
    select,
    step,
    seek,
    reload,
  }
})
