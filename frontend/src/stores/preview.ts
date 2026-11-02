import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'

import { ApiError, apiQuiet, clientBaseUrl, unwrap } from '@/api/client'
import type { FrameLink, Frames, JobSettings } from '@/api/types'
import { latestRequest } from '@/editor/latest'

import { EDIT_DEBOUNCE, useEditorStore } from './editor'
import { useSettingsStore } from './settings'

/** What the preview panel shows of the current frame. */
export type ViewMode = 'source' | 'output' | 'split' | 'side'

/** `fit` the panel, or 1 (100 %) or 2 (200 %) CSS pixels per source pixel. */
export type Zoom = 'fit' | 1 | 2

/** A point of the source picture as FFmpeg decodes it, in pixels from its top-left corner. */
export interface SourcePoint {
  x: number
  y: number
}

function reason(failure: unknown): string {
  return failure instanceof ApiError ? failure.problem.title : String(failure)
}

// The link is relative to the server, which is not the page's origin in the desktop app.
function absolute(frame: FrameLink): FrameLink {
  return { ...frame, url: new URL(frame.url, clientBaseUrl() || globalThis.location.origin).href }
}

function framesOf(answer: Frames, kind: FrameLink['kind']): FrameLink[] {
  return answer.frames.filter((frame) => frame.kind === kind).map(absolute)
}

/** What the output frame is made of: another edit keeps the frame. */
function pictureKey(job: JobSettings): string {
  return JSON.stringify([job.source, job.dimensions, job.filters, job.video, job.subtitles])
}

/**
 * The preview panel's frames: the strip of the shown file, the current frame, the output frame
 * of the editor's job, the view mode, the zoom and the pointer over the picture.
 */
export const usePreviewStore = defineStore('preview', () => {
  const editor = useEditorStore()
  const settings = useSettingsStore()

  /** The file the frames are of: the editor's shown file; `null` when none is shown. */
  const sourceId = computed<string | null>(() => editor.target?.sourceId ?? null)
  /** Evenly spaced source frames (Settings → Preview's count), in timestamp order. */
  const strip = shallowRef<FrameLink[]>([])
  /** The answer's notes (how an HDR picture was mapped for display, frames left out). */
  const notes = ref<string[]>([])
  const loading = ref(false)
  /** Why the strip could not be made (the problem's title). */
  const error = ref<string | null>(null)
  /** The strip frame shown; `null` when a seek shows a frame between them. */
  const index = ref<number | null>(null)
  /** The frame of the last seek, shown while `index` is `null`. */
  const sought = shallowRef<FrameLink | null>(null)
  const seeking = ref(false)
  /** Why the last seek shows no frame: the server's note, or the problem's title. */
  const seekNote = ref<string | null>(null)
  /** The source frame shown: a strip frame, or the frame of the last seek. */
  const current = computed<FrameLink | null>(() =>
    index.value === null ? sought.value : (strip.value[index.value] ?? null),
  )
  /**
   * The output frame of the editor's job at `current`'s time (`preview/render`), while the panel
   * shows a view mode that needs it; `null` while it is on its way or out of date.
   */
  const output = shallowRef<FrameLink | null>(null)
  const rendering = ref(false)
  /** Why there is no output frame: the problem's title, or the note of a job FFmpeg refused. */
  const renderError = ref<string | null>(null)
  /** The render's notes (burned-in subtitles left out, a copied video). */
  const renderNotes = ref<string[]>([])
  const viewMode = ref<ViewMode>('source')
  const zoom = ref<Zoom>('fit')
  /** The pointer over the shown source picture; `null` when it is elsewhere. */
  const pointer = ref<SourcePoint | null>(null)
  /** The preview panel is mounted and not collapsed: only then is an output frame asked for. */
  const panelOpen = ref(false)

  let stripRequest: AbortController | null = null
  let seekRequest: AbortController | null = null
  // A frame link expires after a few minutes. A failed image asks again once per frame shown,
  // so a link that never loads cannot ask in a loop.
  const retried = new Set<string>()

  async function loadStrip(id: string): Promise<void> {
    stripRequest?.abort()
    const own = new AbortController()
    stripRequest = own
    loading.value = true
    error.value = null
    try {
      const answer = unwrap(
        await apiQuiet.POST('/api/preview/frames', {
          body: { source_id: id },
          signal: own.signal,
        }),
      )
      if (stripRequest !== own) return
      const frames = framesOf(answer, 'source')
      strip.value = frames
      notes.value = answer.notes
      if (index.value !== null && index.value >= frames.length) index.value = null
      if (index.value === null && sought.value === null && frames.length > 0) index.value = 0
    } catch (failure) {
      if (stripRequest !== own) return
      strip.value = []
      notes.value = []
      if (index.value !== null) index.value = null
      error.value = reason(failure)
    } finally {
      if (stripRequest === own) {
        stripRequest = null
        loading.value = false
      }
    }
  }

  // An aborted request makes the server cancel its frames task.
  function forgetFile(): void {
    stripRequest?.abort()
    stripRequest = null
    seekRequest?.abort()
    seekRequest = null
    retried.clear()
    strip.value = []
    notes.value = []
    loading.value = false
    error.value = null
    index.value = null
    sought.value = null
    seeking.value = false
    seekNote.value = null
    renderNotes.value = []
    pointer.value = null
  }

  /** Shows strip frame `at`. */
  function select(at: number): void {
    if (at < 0 || at >= strip.value.length) return
    retried.clear()
    seekRequest?.abort()
    seekRequest = null
    seeking.value = false
    seekNote.value = null
    index.value = at
  }

  /** The next (1) or previous (-1) strip frame; after a seek, the one next to its time. */
  function step(delta: 1 | -1): void {
    const frames = strip.value
    if (frames.length === 0) return
    let next: number
    if (index.value !== null) {
      next = index.value + delta
    } else {
      const time = sought.value?.timestamp ?? 0
      next =
        delta === 1
          ? frames.findIndex((frame) => frame.timestamp > time)
          : frames.findLastIndex((frame) => frame.timestamp < time)
    }
    select(next)
  }

  /** Shows the source frame at `seconds` (`preview/frames` with that timestamp). */
  async function seek(seconds: number): Promise<void> {
    retried.clear()
    await askFrame(seconds)
  }

  async function askFrame(seconds: number): Promise<void> {
    const id = sourceId.value
    if (id === null) return
    seekRequest?.abort()
    const own = new AbortController()
    seekRequest = own
    seeking.value = true
    seekNote.value = null
    try {
      const answer = unwrap(
        await apiQuiet.POST('/api/preview/frames', {
          body: { source_id: id, timestamps: [seconds] },
          signal: own.signal,
        }),
      )
      if (seekRequest !== own) return
      const frame = framesOf(answer, 'source')[0]
      if (frame === undefined) {
        seekNote.value = answer.notes.join(' ')
        return
      }
      sought.value = frame
      index.value = null
    } catch (failure) {
      if (seekRequest !== own) return
      seekNote.value = reason(failure)
    } finally {
      if (seekRequest === own) {
        seekRequest = null
        seeking.value = false
      }
    }
  }

  /** Asks for the strip again (its URLs have expired, or it failed). */
  async function reload(): Promise<void> {
    const id = sourceId.value
    if (id !== null) await loadStrip(id)
  }

  const render = latestRequest<Frames>({
    async send(signal) {
      const job = editor.job as JobSettings
      const timestamp = (current.value as FrameLink).timestamp
      return unwrap(
        await apiQuiet.POST('/api/preview/render', { body: { job, timestamp }, signal }),
      )
    },
    done(answer) {
      const frame = framesOf(answer, 'output')[0] ?? null
      output.value = frame
      renderNotes.value = frame === null ? [] : answer.notes
      renderError.value = frame === null ? answer.notes.join(' ') : null
      rendering.value = false
    },
    failed(failure) {
      output.value = null
      renderNotes.value = []
      renderError.value = reason(failure)
      rendering.value = false
    },
  })

  const needsOutput = computed(() => panelOpen.value && viewMode.value !== 'source')
  /** What the output frame depends on; `null` when none is wanted. */
  const renderKey = computed(() => {
    const job = editor.job
    const frame = current.value
    if (!needsOutput.value || job === null || frame === null) return null
    return JSON.stringify([frame.key, pictureKey(job)])
  })
  // An edit waits for the next one; a new frame, view or file is asked for at once.
  let lastFrame: string | null = null

  function scheduleRender(): void {
    const key = renderKey.value
    output.value = null
    renderError.value = null
    if (key === null) {
      render.cancel()
      rendering.value = false
      lastFrame = null
      return
    }
    const frame = (current.value as FrameLink).key
    const edit = lastFrame === frame
    lastFrame = frame
    rendering.value = true
    render.schedule(edit ? EDIT_DEBOUNCE : 0)
  }

  // Registered first: a new job is asked for at once, not after the edit delay.
  watch(
    () => editor.session,
    () => {
      lastFrame = null
    },
  )
  watch(renderKey, scheduleRender)

  watch(
    [sourceId, () => settings.settings?.preview?.sample_frames],
    ([id], [previous]) => {
      if (id !== previous) forgetFile()
      if (id !== null) void loadStrip(id)
    },
    { immediate: true },
  )

  /**
   * An image of `frame` did not load. The first time per frame shown, its link is asked for
   * again (it may have expired); returns `false` when it has been asked for already.
   */
  function imageFailed(frame: FrameLink): boolean {
    const isSought =
      frame.kind === 'source' && index.value === null && sought.value?.key === frame.key
    // One strip answer gives every thumbnail: a failed strip is asked for once, not per image.
    const key = frame.kind === 'output' || isSought ? `${frame.kind}:${frame.key}` : 'strip'
    if (retried.has(key)) return false
    retried.add(key)
    if (frame.kind === 'output') {
      output.value = null
      rendering.value = true
      render.schedule(0)
    } else if (isSought) {
      void askFrame(frame.timestamp)
    } else {
      void reload()
    }
    return true
  }

  return {
    sourceId,
    strip,
    notes,
    loading,
    error,
    index,
    current,
    sought,
    seeking,
    seekNote,
    output,
    rendering,
    renderError,
    renderNotes,
    viewMode,
    zoom,
    pointer,
    panelOpen,
    select,
    step,
    seek,
    reload,
    imageFailed,
  }
})
