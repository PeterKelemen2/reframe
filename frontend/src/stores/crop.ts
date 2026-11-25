import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type { CropDetection, CropRect, CropSettings, ValidationIssue } from '@/api/types'
import {
  appliedCrop,
  type CropGrid,
  EDGES,
  gridOf,
  NO_CROP,
  snapCrop,
  type SnapChange,
} from '@/components/dimensions/grid'
import { useGeometry } from '@/components/summary/useGeometry'
import { useJobSource } from '@/components/summary/useJobSource'

import { type PatchOptions, useEditorStore } from './editor'
import { useSettingsStore } from './settings'
import { useTasksStore } from './tasks'
import { useValidationStore } from './validation'

export type CropMode = CropSettings['mode']

export interface PictureSize {
  width: number
  height: number
}

export interface RectOptions extends PatchOptions {
  /** A handle moved the edge: the user sees where it went, so no note explains it. */
  quiet?: boolean
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

/** The crop a mode was chosen on is still there; the detected rectangle filled in does not count. */
function unchanged(before: CropSettings | undefined, now: CropSettings | undefined): boolean {
  if (before?.mode !== now?.mode) return false
  return before?.rect == null || JSON.stringify(before.rect) === JSON.stringify(now?.rect)
}

/** A crop with its edges named, in the order top, bottom, left, right: `T 22 · B 24 · L 0 · R 0`. */
function cropText(rect: CropRect): string {
  return text('dimensions.crop.rect', { ...rect })
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
  const settings = useSettingsStore()
  const validation = useValidationStore()
  const answer = useGeometry()
  const { source } = useJobSource()

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
  /** Why the last change was moved onto the chroma grid; `null` when nothing moved. */
  const snapNote = ref<string | null>(null)

  const files = shallowRef<Record<string, FileDetection>>({})
  const shownId = computed(() => editor.target?.sourceId ?? null)

  /** A detection is of a file and of the sample count: it runs on the strip's sample times. */
  function keyOf(sourceId: string): string {
    return `${sourceId} ${settings.settings?.preview?.sample_frames ?? ''}`
  }

  const shown = computed<FileDetection | null>(() =>
    shownId.value === null ? null : (files.value[keyOf(shownId.value)] ?? null),
  )
  /** Crop detection of the shown file on the strip's sample times, kept per file for the page. */
  const detection = computed<CropDetection | null>(() => shown.value?.result ?? null)
  const detecting = computed(() => (shown.value?.running ?? null) !== null)
  const detectionError = computed<string | null>(() => shown.value?.error ?? null)

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

  /** The shown file has no video stream, as its probe or `jobs/geometry` says. */
  const noVideo = computed(
    () =>
      (source.value !== null && (source.value.video ?? []).length === 0) ||
      geometry.value?.source === null,
  )
  /** The job changes the picture: it does not copy the video, and the file has a video stream. */
  const pictureEditable = computed(
    () => editor.job !== null && editor.job.video?.passthrough !== true && !noVideo.value,
  )
  /** Manual mode: the inputs, the drag handles and the arrow keys change the crop. */
  const editable = computed(() => mode.value === 'manual' && pictureEditable.value)

  /**
   * The sample frames disagree on the black bars: what the most common bars are, on how many
   * frames; `null` when every frame has the same.
   */
  const disagreement = computed<{ rect: CropRect; frames: number; total: number } | null>(() => {
    const found = detection.value
    if (found === null || EDGES.every((edge) => found.auto[edge] === found.conservative[edge])) {
      return null
    }
    return { rect: found.auto, frames: found.auto_frames, total: found.samples.length }
  })

  /**
   * The crop removes more than is black on every sample frame: on the other frames it can remove
   * picture. Only automatic mode applies such a crop by itself.
   */
  const issues = computed<ValidationIssue[]>(() => {
    const found = detection.value
    const applied = rect.value
    const crop = editor.job?.dimensions?.crop
    if (
      editor.target?.kind !== 'job' ||
      crop?.mode !== 'auto' ||
      !pictureEditable.value ||
      found === null ||
      applied === null ||
      EDGES.every((edge) => applied[edge] <= found.conservative[edge])
    ) {
      return []
    }
    const safe = found.conservative
    return [
      {
        severity: 'warning',
        code: 'dimensions.crop_frames_disagree',
        path: 'dimensions.crop',
        message: text('dimensions.disagree.issue', {
          rect: cropText(applied),
          safe: cropText(safe),
        }),
        fixes: [
          {
            label: text('dimensions.disagree.conservative'),
            target: 'job',
            patch: [
              {
                op: 'replace',
                path: '/dimensions/crop',
                value: { ...crop, mode: 'conservative', rect: { ...safe } },
              },
            ],
          },
        ],
      },
    ]
  })
  validation.addLocal('crop', () => issues.value)

  function put(key: string, change: Partial<FileDetection>): void {
    const known = files.value[key] ?? { result: null, error: null, running: null }
    files.value = { ...files.value, [key]: { ...known, ...change } }
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
    const key = keyOf(sourceId)
    const known = files.value[key]?.running
    if (known) return known
    const running = run(sourceId).then(
      (result) => {
        put(key, { result, error: null, running: null })
        return result
      },
      (error: Error) => {
        const reason = error instanceof ApiError ? error.problem.title : error.message
        put(key, { error: reason, running: null })
        throw error
      },
    )
    put(key, { error: null, running })
    return running
  }

  /** Runs crop detection on the shown file again. */
  function detect(): Promise<CropDetection> {
    const sourceId = shownId.value
    if (sourceId === null) return Promise.reject(new Error('crop.detect: no file is shown'))
    return detectFile(sourceId)
  }

  // Once per file and sample count for the page: a file shown again keeps its detection (or its
  // failure).
  watch(
    [shownId, () => settings.settings?.preview?.sample_frames, noVideo],
    ([sourceId, , none]) => {
      if (sourceId !== null && !none && files.value[keyOf(sourceId)] === undefined) {
        detectFile(sourceId).catch(() => {})
      }
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
      const found = all[keyOf(target.sourceId)]?.result
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

  /** The crop with `mode` and `rect` replaced: a field of a newer version stays. */
  function writeCrop(next: Pick<CropSettings, 'mode' | 'rect'>, options?: PatchOptions): void {
    const crop = { ...editor.job?.dimensions?.crop, ...next }
    noted = JSON.stringify(crop)
    editor.set('/dimensions/crop', crop, options)
  }

  /**
   * A manual crop: snapped down to the chroma grid and kept inside the picture, the mode set to
   * manual; one undo step, or part of the run of `options.coalesce` (a drag, held arrow keys).
   */
  function setRect(next: CropRect, options?: RectOptions): void {
    if (grid.value === null) return
    const { rect: snapped, changes } = snapCrop(next, rect.value ?? NO_CROP, grid.value)
    const current = grid.value
    snapNote.value =
      changes.length === 0 || options?.quiet
        ? null
        : changes.map((change) => noteOf(change, current)).join(' · ')
    writeCrop({ mode: 'manual', rect: snapped }, { coalesce: options?.coalesce })
  }

  /**
   * Another mode, one undo step. Automatic and conservative take the detected rectangle; the
   * detection runs first when it has not. A group's files are queued without detection: it gets
   * the mode only.
   */
  async function setMode(next: CropMode): Promise<void> {
    const target = editor.target
    if (target === null || next === mode.value) return
    if (!detected(next)) {
      const kept = next === 'manual' ? (rect.value ?? { ...NO_CROP }) : null
      writeCrop({ mode: next, rect: kept })
      return
    }
    if (target.kind === 'group') {
      writeCrop({ mode: next, rect: null })
      return
    }
    const session = editor.session
    const before = target.job.dimensions?.crop
    let found = files.value[keyOf(target.sourceId)]?.result ?? null
    if (found === null) found = await detect().catch(() => null)
    // Another job, or another crop chosen while the detection ran: the last choice stands.
    if (editor.session !== session || !unchanged(before, editor.job?.dimensions?.crop)) return
    writeCrop({ mode: next, rect: found?.[next] ?? null })
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
    pictureEditable,
    detection,
    disagreement,
    issues,
    detecting,
    detectionError,
    snapNote,
    setRect,
    setMode,
    detect,
  }
})
