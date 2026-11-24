import { until } from '@vueuse/core'
import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type { FrameLink, Geometry, JobSettings, PreviewClip } from '@/api/types'
import { CLIP_LENGTHS, millis, reason } from '@/components/clip/clip'

import { useCropStore } from './crop'
import { useEditorStore } from './editor'
import { usePreviewStore } from './preview'
import { TaskLostError, useTasksStore } from './tasks'

/** A clip and what it was made from. */
export interface MadeClip {
  clip: PreviewClip
  sourceId: string
  /** The job as it was sent. */
  job: JobSettings
}

/** A clip's frames beside the source's, decoded once for the frame compare. */
export interface DecodedClip {
  pairs: { time: number; before: FrameLink; after: FrameLink }[]
  geometry: Geometry | null
  notes: string[]
}

/** Decoded clips kept; the oldest is dropped beyond. */
const DECODED_KEPT = 20

/** What a clip shows: the file, its start frame, the length asked for and the job's settings. */
function clipKey(sourceId: string, start: number, seconds: number, job: JobSettings): string {
  return JSON.stringify([sourceId, millis(start), seconds, job])
}

/**
 * The preview clips of the open file, one for each start frame, length and job: the panel shows
 * the one made from what it shows now, so a change of the frame or the job hides a clip and
 * changing back shows it again. A store, so that the panel and the large preview share them and
 * an encode outlives either.
 */
export const useClipsStore = defineStore('clips', () => {
  const editor = useEditorStore()
  const crop = useCropStore()
  const preview = usePreviewStore()
  const tasks = useTasksStore()

  const length = ref<number>(CLIP_LENGTHS[0])
  const clips = shallowRef<ReadonlyMap<string, MadeClip>>(new Map())
  const starting = ref(false)
  const taskId = ref<string | null>(null)
  const encodeError = ref<string | null>(null)
  const cancelled = ref(false)
  // Cancel came before the server named the task.
  const stopAsked = ref(false)
  const decoded = new Map<string, DecodedClip>()

  const running = computed(() => starting.value || taskId.value !== null)
  const progress = computed(() => {
    const value = taskId.value === null ? null : tasks.tasks[taskId.value]?.progress
    return typeof value === 'number' ? value : null
  })
  // A detected crop enters the job when its detection ends: a clip sent before that keeps the bars.
  const cropPending = computed(() => {
    const settings = editor.job?.dimensions?.crop
    return (
      (settings?.mode === 'auto' || settings?.mode === 'conservative') &&
      !settings.rect &&
      crop.detecting
    )
  })

  /** The clip of the shown frame, the chosen length and the job as it is; `null`: none yet. */
  const shown = computed<MadeClip | null>(() => {
    const sourceId = preview.sourceId
    const frame = preview.current
    if (sourceId === null || frame === null || editor.job === null) return null
    return clips.value.get(clipKey(sourceId, frame.timestamp, length.value, editor.job)) ?? null
  })
  /** The file has clips, none of them of the shown frame, length and job. */
  const othersOnly = computed(() => shown.value === null && clips.value.size > 0)

  function keep(key: string, made: MadeClip): void {
    clips.value = new Map(clips.value).set(key, made)
  }

  async function encode(): Promise<void> {
    const frame = preview.current
    const sourceId = preview.sourceId
    const seconds = length.value
    if (editor.job === null || frame === null || sourceId === null) return
    encodeError.value = null
    cancelled.value = false
    stopAsked.value = false
    starting.value = true
    let id: string
    let job: JobSettings
    try {
      await until(() => !cropPending.value || stopAsked.value).toBe(true)
      if (stopAsked.value || editor.job === null) {
        cancelled.value = preview.sourceId === sourceId
        return
      }
      job = editor.job
      id = unwrap(
        await apiQuiet.POST('/api/preview/clip', {
          body: { job, start: frame.timestamp, seconds },
        }),
      ).task_id
    } catch (failure) {
      encodeError.value = reason(failure)
      return
    } finally {
      starting.value = false
    }
    if (stopAsked.value || preview.sourceId !== sourceId) {
      void stop(id)
      cancelled.value = preview.sourceId === sourceId
      return
    }
    taskId.value = id
    try {
      const task = await tasks.wait(id)
      if (taskId.value !== id) return
      if (task.state === 'done') {
        const clip = task.result as unknown as PreviewClip
        keep(clipKey(sourceId, frame.timestamp, seconds, job), { clip, sourceId, job })
      } else if (task.state === 'failed') {
        encodeError.value = task.error ?? text('clip.failedWithoutReason')
      } else {
        cancelled.value = true
      }
    } catch (failure) {
      if (!(failure instanceof TaskLostError)) throw failure
      if (taskId.value === id) encodeError.value = failure.message
    } finally {
      if (taskId.value === id) taskId.value = null
    }
  }

  async function cancel(): Promise<void> {
    if (taskId.value === null) stopAsked.value = true
    else await stop(taskId.value)
  }

  async function stop(id: string): Promise<void> {
    try {
      await tasks.cancel(id)
    } catch (error) {
      // The task ended first; the API client has shown the refusal as a toast.
      if (!(error instanceof ApiError)) throw error
    }
  }

  function decodedClip(clipId: string): DecodedClip | null {
    return decoded.get(clipId) ?? null
  }

  function keepDecoded(clipId: string, value: DecodedClip): void {
    decoded.delete(clipId)
    decoded.set(clipId, value)
    for (const old of decoded.keys()) {
      if (decoded.size <= DECODED_KEPT) break
      decoded.delete(old)
    }
  }

  // Another file drops the clips and stops an encode of the last one.
  watch(
    () => preview.sourceId,
    () => {
      if (running.value) void cancel()
      taskId.value = null
      encodeError.value = null
      cancelled.value = false
      clips.value = new Map()
      decoded.clear()
    },
  )

  return {
    length,
    starting,
    taskId,
    encodeError,
    cancelled,
    running,
    progress,
    cropPending,
    shown,
    othersOnly,
    encode,
    cancel,
    decodedClip,
    keepDecoded,
  }
})
