import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type { CropDetection, CropRect, CropSettings } from '@/api/types'
import {
  appliedCrop,
  type CropGrid,
  gridOf,
  NO_CROP,
  snapCrop,
  type SnapChange,
} from '@/components/dimensions/grid'
import { useGeometry } from '@/components/summary/useGeometry'

import { type PatchOptions, useEditorStore } from './editor'
import { useTasksStore } from './tasks'

export type CropMode = CropSettings['mode']

export interface PictureSize {
  width: number
  height: number
}

/** One file's crop detection: kept for the page. */
interface FileDetection {
  result: CropDetection | null
  error: string | null
  running: Promise<CropDetection> | null
}

function detected(mode: CropMode | null): mode is 'auto' | 'conservative' {
  return mode === 'auto' || mode === 'conservative'
}

function noteOf(change: SnapChange, grid: CropGrid): string {
  const named = {
    edge: text(`dimensions.crop.edges.${change.edge}`),
    from: change.from,
    to: change.to,
  }
  switch (change.reason) {
    case 'grid':
      return text(grid.interlaced ? 'dimensions.snap.gridInterlaced' : 'dimensions.snap.grid', {
        ...named,
        grid: grid.subsampling,
      })
    case 'size': {
      const across = change.edge === 'right'
      return text(across ? 'dimensions.snap.width' : 'dimensions.snap.height', {
        ...named,
        step: across ? grid.stepX : grid.stepY,
      })
    }
    case 'inside':
      return text('dimensions.snap.inside', named)
  }
}

/**
 * The editor job's picture: `jobs/geometry`, the crop and its detection. A crop is measured on
 * the source picture as FFmpeg decodes it (display matrix applied, the job's rotation not yet).
 */
export const useCropStore = defineStore('crop', () => {
  const editor = useEditorStore()
  const tasks = useTasksStore()
  const answer = useGeometry()

  /** `jobs/geometry` of the editor's job, the newest answer: the pipeline header, the grid. */
  const geometry = answer.answer
  /** Why the server could not compute it (the problem's title). */
  const geometryError = answer.error
  /** A `jobs/geometry` request is waiting for its debounce or its answer. */
  const geometryPending = answer.pending

  /** The picture the crop is measured on and its chroma grid; `null` like `sourceSize`. */
  const grid = computed<CropGrid | null>(() =>
    geometry.value?.source ? gridOf(geometry.value.source) : null,
  )

  /** The job's crop mode; `null` when no job is open. */
  const mode = computed<CropMode | null>(() => editor.job?.dimensions?.crop?.mode ?? null)
  /** Crop detection of the shown file on the strip's sample times, kept per file for the page. */
  const detection = shallowRef<CropDetection | null>(null)
  const detecting = ref(false)
  const detectionError = ref<string | null>(null)
  /** Why the last change was moved onto the chroma grid; `null` when nothing moved. */
  const snapNote = ref<string | null>(null)

  /**
   * The crop the job applies, on the chroma grid: the manual rectangle, or the detected one in
   * automatic and conservative mode; `null` for no crop, before detection, or with no job.
   */
  const rect = computed<CropRect | null>(() => {
    const crop = editor.job?.dimensions?.crop
    if (!crop || crop.mode === 'none' || grid.value === null) return null
    const requested = crop.rect ?? (detected(crop.mode) ? detection.value?.[crop.mode] : null)
    return requested ? appliedCrop(requested, grid.value) : null
  })
  /** The source picture as decoded; `null` until `geometry` has come or without video. */
  const sourceSize = computed<PictureSize | null>(() =>
    grid.value === null ? null : { width: grid.value.width, height: grid.value.height },
  )
  /** Manual mode: the inputs, the drag handles and the arrow keys change the crop. */
  const editable = computed(() => mode.value === 'manual')

  const files = shallowRef<Record<string, FileDetection>>({})
  const shownId = computed(() => editor.target?.sourceId ?? null)

  function put(sourceId: string, change: Partial<FileDetection>): void {
    const known = files.value[sourceId] ?? { result: null, error: null, running: null }
    files.value = { ...files.value, [sourceId]: { ...known, ...change } }
  }

  async function run(sourceId: string): Promise<CropDetection> {
    const accepted = unwrap(
      await apiQuiet.POST('/api/preview/cropdetect', { body: { source_id: sourceId } }),
    )
    const task = await tasks.wait(accepted.task_id)
    if (task.state !== 'done') {
      throw new Error(task.error ?? text('dimensions.detection.cancelled'))
    }
    return task.result as unknown as CropDetection
  }

  function detectFile(sourceId: string): Promise<CropDetection> {
    const known = files.value[sourceId]?.running
    if (known) return known
    const running = run(sourceId).then(
      (result) => {
        put(sourceId, { result, error: null, running: null })
        return result
      },
      (error: Error) => {
        const reason = error instanceof ApiError ? error.problem.title : error.message
        put(sourceId, { error: reason, running: null })
        throw error
      },
    )
    put(sourceId, { error: null, running })
    return running
  }

  /** Runs crop detection on the shown file again. */
  function detect(): Promise<CropDetection> {
    const sourceId = shownId.value
    if (sourceId === null) return Promise.reject(new Error('crop.detect: no file is shown'))
    return detectFile(sourceId)
  }

  // Once per file for the page: a file shown again keeps its detection (or its failure).
  watch(
    shownId,
    (sourceId) => {
      if (sourceId !== null && files.value[sourceId] === undefined) {
        detectFile(sourceId).catch(() => {})
      }
    },
    { immediate: true },
  )

  watch(
    [shownId, files],
    ([sourceId, all]) => {
      const file = sourceId === null ? undefined : all[sourceId]
      detection.value = file?.result ?? null
      detecting.value = (file?.running ?? null) !== null
      detectionError.value = file?.error ?? null
    },
    { immediate: true },
  )

  // A single job in a detected mode without a rectangle takes its file's detection, as the
  // server would have worked it out: no undo step, and not a change against the preset.
  watch(
    [() => editor.target, files],
    ([target, all]) => {
      if (target?.kind !== 'job') return
      const crop = target.job.dimensions?.crop
      const found = all[target.sourceId]?.result
      if (!crop || !detected(crop.mode) || crop.rect || !found) return
      editor.amend([{ op: 'add', path: '/dimensions/crop/rect', value: found[crop.mode] }])
    },
    { immediate: true },
  )

  // The note explains the rectangle that `setRect` stored; an undo, another mode or another job
  // takes it away.
  let noted: string | null = null
  watch(
    () => JSON.stringify(editor.job?.dimensions?.crop ?? null),
    (crop) => {
      if (crop !== noted) snapNote.value = null
    },
  )

  /**
   * A manual crop: snapped down to the chroma grid and kept inside the picture, the mode set to
   * manual; one undo step, or part of the run of `options.coalesce` (a drag, held arrow keys).
   */
  function setRect(next: CropRect, options?: PatchOptions): void {
    if (grid.value === null) return
    const { rect: snapped, changes } = snapCrop(next, rect.value ?? NO_CROP, grid.value)
    const current = grid.value
    snapNote.value =
      changes.length === 0 ? null : changes.map((change) => noteOf(change, current)).join(' · ')
    const crop = { mode: 'manual', rect: snapped }
    noted = JSON.stringify(crop)
    editor.set('/dimensions/crop', crop, options)
  }

  /**
   * Another mode, one undo step. Automatic and conservative take the detected rectangle; the
   * detection runs first when it has not. A group's files detect their own crop: it gets the
   * mode only.
   */
  async function setMode(next: CropMode): Promise<void> {
    const target = editor.target
    if (target === null || next === mode.value) return
    if (!detected(next)) {
      const kept = next === 'manual' ? (rect.value ?? { ...NO_CROP }) : null
      editor.set('/dimensions/crop', { mode: next, rect: kept })
      return
    }
    if (target.kind === 'group') {
      editor.set('/dimensions/crop', { mode: next, rect: null })
      return
    }
    const session = editor.session
    let found = files.value[target.sourceId]?.result ?? null
    if (found === null) found = await detect().catch(() => null)
    // Another job opened while the detection ran: the mode was meant for the last one.
    if (editor.session !== session) return
    editor.set('/dimensions/crop', { mode: next, rect: found?.[next] ?? null })
  }

  return {
    geometry,
    geometryError,
    geometryPending,
    grid,
    mode,
    rect,
    sourceSize,
    editable,
    detection,
    detecting,
    detectionError,
    snapNote,
    setRect,
    setMode,
    detect,
  }
})
