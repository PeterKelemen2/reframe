import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import type { CropDetection, CropRect, CropSettings, JobGeometry } from '@/api/types'
import { notBuilt } from '@/notBuilt'

import type { PatchOptions } from './editor'

export type CropMode = CropSettings['mode']

export interface PictureSize {
  width: number
  height: number
}

/**
 * The editor job's picture: `jobs/geometry`, the crop and its detection. A crop is measured on
 * the source picture as FFmpeg decodes it (display matrix applied, the job's rotation not yet;
 * decision 0009 item 1).
 */
export const useCropStore = defineStore('crop', () => {
  /** `jobs/geometry` of the editor's job, the newest answer: the pipeline header, the grid. */
  const geometry = shallowRef<JobGeometry | null>(null)
  /** Why the server could not compute it (the problem's title). */
  const geometryError = ref<string | null>(null)
  /** The job's crop mode; `null` when no job is open. */
  const mode = computed<CropMode | null>(() => null)
  /**
   * The crop the job applies, on the chroma grid: the manual rectangle, or the detected one in
   * automatic and conservative mode; `null` for no crop, before detection, or with no job.
   */
  const rect = computed<CropRect | null>(() => null)
  /** The source picture as decoded; `null` until `geometry` has come or without video. */
  const sourceSize = computed<PictureSize | null>(() => null)
  /** Manual mode: the inputs, the drag handles and the arrow keys change the crop. */
  const editable = computed(() => false)
  /** Crop detection of the shown file on the strip's sample times, kept per file for the page. */
  const detection = shallowRef<CropDetection | null>(null)
  const detecting = ref(false)
  const detectionError = ref<string | null>(null)
  /** Why the last change was moved onto the chroma grid; `null` when nothing moved. */
  const snapNote = ref<string | null>(null)

  /* oxlint-disable unicorn/consistent-function-scoping -- the stubs until task B builds them */
  /**
   * A manual crop: snapped down to the chroma grid and kept inside the picture, the mode set to
   * manual; one undo step, or part of the run of `options.coalesce` (a drag, held arrow keys).
   */
  function setRect(next: CropRect, options?: PatchOptions): void {
    notBuilt('crop.setRect', next, options)
  }

  /**
   * Another mode, one undo step. Automatic and conservative take the detected rectangle; the
   * detection runs first when it has not.
   */
  async function setMode(next: CropMode): Promise<void> {
    notBuilt('crop.setMode', next)
  }

  /** Runs crop detection on the shown file again. */
  async function detect(): Promise<CropDetection> {
    return notBuilt('crop.detect')
  }
  /* oxlint-enable unicorn/consistent-function-scoping */

  return {
    geometry,
    geometryError,
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
