import { defineStore } from 'pinia'
import { reactive, ref, watch } from 'vue'

import { api, ApiError, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type { BitrateScan, LoudnessMeasurement, TaskInfo } from '@/api/types'

import { useSourcesStore } from './sources'
import { TaskLostError, useTasksStore } from './tasks'
import { useToastStore } from './toasts'

export type ScanKind = 'bitrate' | 'subtitle' | 'loudness'

/** A scan task that has not ended. */
export interface ScanRun {
  sourceId: string
  kind: ScanKind
  /** The stream it measures; `null` for a subtitle scan of every subtitle track. */
  streamIndex: number | null
  taskId: string
  /** 0..1; `null` until the task reports one. */
  progress: number | null
}

type Target = Pick<ScanRun, 'sourceId' | 'kind' | 'streamIndex'>

const TOAST_LIFE = 10_000

function keyOf(target: Target): string {
  return `${target.sourceId}:${target.kind}:${target.streamIndex ?? '*'}`
}

function failedSummary(kind: ScanKind): string {
  switch (kind) {
    case 'bitrate':
      return text('media.scan.failed.bitrate')
    case 'subtitle':
      return text('media.scan.failed.subtitle')
    case 'loudness':
      return text('media.scan.failed.loudness')
  }
  return kind
}

/**
 * The **Measure** scans of a source's streams: each one a cancellable server task. When a
 * bitrate or subtitle scan ends, the source is read again (`sources.reload`), so its tables
 * show the measured values.
 */
export const useScansStore = defineStore('scans', () => {
  const tasks = useTasksStore()
  const sources = useSourcesStore()
  const toasts = useToastStore()

  const runs = ref<ScanRun[]>([])
  /** The last loudness measurement per `sourceId:streamIndex` (the source does not keep it). */
  const loudness = ref<Record<string, LoudnessMeasurement>>({})
  // One promise per target from the click on: a second click joins the scan instead of
  // starting another task, also before the server has answered the first.
  const pending = new Map<string, Promise<unknown>>()

  // The getter reads only the task ids, so the progress written into the runs does not
  // trigger it again.
  watch(
    () => runs.value.map((run) => tasks.tasks[run.taskId]),
    (infos) => {
      runs.value.forEach((run, index) => {
        const info = infos[index]
        if (info === undefined) return
        run.progress = typeof info.progress === 'number' ? info.progress / 100 : null
      })
    },
  )

  /** The run of this scan, if one is going. A subtitle scan of every track has no stream. */
  function running(
    sourceId: string,
    kind: ScanKind,
    streamIndex: number | null = null,
  ): ScanRun | undefined {
    return runs.value.find(
      (run) => run.sourceId === sourceId && run.kind === kind && run.streamIndex === streamIndex,
    )
  }

  function fail(kind: ScanKind, detail: string | null | undefined): void {
    toasts.push({
      severity: 'error',
      summary: failedSummary(kind),
      detail: detail ?? undefined,
      life: TOAST_LIFE,
    })
  }

  /**
   * Starts the task (a refusal is the client's toast), shows it in `runs` until `finish` has
   * run, and gives `finish`'s value for a `done` task, else `none`. A failure is a toast; a
   * cancel is quiet.
   */
  function scan<T>(
    target: Target,
    start: () => Promise<string>,
    finish: (task: TaskInfo) => Promise<T>,
    none: T,
  ): Promise<T> {
    const key = keyOf(target)
    const known = pending.get(key)
    if (known !== undefined) return known as Promise<T>
    const promise = (async (): Promise<T> => {
      let taskId: string
      try {
        taskId = await start()
      } catch (error) {
        if (error instanceof ApiError) return none
        throw error
      }
      const run = reactive<ScanRun>({ ...target, taskId, progress: null })
      runs.value.push(run)
      try {
        const task = await tasks.wait(taskId)
        if (task.state === 'done') return await finish(task)
        if (task.state === 'failed') fail(target.kind, task.error)
        return none
      } catch (error) {
        if (!(error instanceof TaskLostError)) throw error
        fail(target.kind, error.message)
        return none
      } finally {
        runs.value = runs.value.filter((other) => other.taskId !== taskId)
      }
    })().finally(() => pending.delete(key))
    pending.set(key, promise)
    return promise
  }

  // A failed reload was a toast already; the scan itself is done.
  async function reload(sourceId: string): Promise<void> {
    try {
      await sources.reload(sourceId)
    } catch (error) {
      if (!(error instanceof ApiError)) throw error
    }
  }

  async function measureBitrate(sourceId: string, streamIndex: number): Promise<void> {
    return scan(
      { sourceId, kind: 'bitrate', streamIndex },
      async () => {
        const accepted = unwrap(
          await api.POST('/api/sources/{source_id}/streams/{index}/bitrate-scan', {
            params: { path: { source_id: sourceId, index: streamIndex } },
          }),
        )
        return accepted.task_id
      },
      async (task) => {
        const result = task.result as unknown as BitrateScan
        if (result.bitrate.value === null || result.bitrate.value === undefined) {
          toasts.push({
            severity: 'warn',
            summary: text('media.scan.noBitrate'),
            detail: text('media.scan.noBitrateDetail'),
            life: TOAST_LIFE,
          })
        }
        await reload(sourceId)
      },
      undefined,
    )
  }

  /**
   * Counts events and forced events; `streamIndexes` omitted: every subtitle track. A scan of
   * one track while every track is being counted joins that scan.
   */
  async function scanSubtitles(sourceId: string, streamIndexes?: number[]): Promise<void> {
    const streamIndex = streamIndexes?.length === 1 ? streamIndexes[0]! : null
    if (streamIndex !== null) {
      const all = pending.get(keyOf({ sourceId, kind: 'subtitle', streamIndex: null }))
      if (all !== undefined) return all as Promise<void>
    }
    return scan(
      { sourceId, kind: 'subtitle', streamIndex },
      async () => {
        const accepted = unwrap(
          await api.POST('/api/sources/{source_id}/subtitle-scan', {
            params: { path: { source_id: sourceId } },
            body: { stream_indexes: streamIndexes ?? null },
          }),
        )
        return accepted.task_id
      },
      async () => reload(sourceId),
      undefined,
    )
  }

  /** `null` when the scan failed or was cancelled (the failure is a toast). */
  async function measureLoudness(
    sourceId: string,
    streamIndex: number,
  ): Promise<LoudnessMeasurement | null> {
    return scan<LoudnessMeasurement | null>(
      { sourceId, kind: 'loudness', streamIndex },
      async () => {
        const accepted = unwrap(
          await api.POST('/api/sources/{source_id}/streams/{index}/loudness', {
            params: { path: { source_id: sourceId, index: streamIndex } },
          }),
        )
        return accepted.task_id
      },
      async (task) => {
        const result = task.result as unknown as LoudnessMeasurement
        loudness.value = { ...loudness.value, [`${sourceId}:${streamIndex}`]: result }
        return result
      },
      null,
    )
  }

  /** Asks the server to cancel; the run ends with the task (a refusal is the client's toast). */
  async function cancel(run: ScanRun): Promise<void> {
    try {
      await tasks.cancel(run.taskId)
    } catch (error) {
      if (!(error instanceof ApiError)) throw error
    }
  }

  return { runs, loudness, running, measureBitrate, scanSubtitles, measureLoudness, cancel }
})
