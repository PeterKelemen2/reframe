// oxlint-disable unicorn/consistent-function-scoping -- stub actions; they use the store once built
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type {
  EventOf,
  JobLogChunk,
  JobSettings,
  JobState,
  QueueJob,
  QueueProcessingEvent,
  WhenDone,
} from '@/api/types'
import { notBuilt } from '@/notBuilt'

export type PowerCountdown = EventOf<'power.countdown'>

/** The server's queue, kept current by events and read again after a lost connection. */
export const useQueueStore = defineStore('queue', () => {
  /** Every job, in queue order. */
  const jobs = ref<QueueJob[]>([])
  /** The runner takes waiting jobs (after a Start, until a Stop). */
  const processing = ref(false)
  /** The runner takes only these jobs (another front end's `start`); `null`: every waiting job. */
  const only = ref<string[] | null>(null)
  const whenDone = ref<WhenDone>('nothing')
  /** The when-done countdown while it runs (`started`, `tick`); `null` otherwise. */
  const power = ref<PowerCountdown | null>(null)
  /** One more for each `job.log` event of a job: a log view that follows the job reads on. */
  const logTicks = ref<Record<string, number>>({})
  const loaded = ref(false)

  const counts = computed<Record<JobState, number>>(() => {
    const result: Record<JobState, number> = {
      waiting: 0,
      running: 0,
      paused: 0,
      done: 0,
      failed: 0,
      cancelled: 0,
      interrupted: 0,
    }
    for (const job of jobs.value) result[job.state] += 1
    return result
  })

  /** 0 to 1 over the running and paused jobs; `null` when none runs (taskbar progress). */
  const overallProgress = computed<number | null>(() => null)

  function byId(id: string): QueueJob | undefined {
    return jobs.value.find((job) => job.id === id)
  }

  /** Adds jobs at the end of the queue (never attached); `start` also starts the queue. */
  async function add(settings: JobSettings[], options?: { start?: boolean }): Promise<QueueJob[]> {
    return notBuilt('queue.add', settings, options)
  }

  /** Start taking waiting jobs; `jobIds`: only these. */
  async function start(jobIds?: string[]): Promise<void> {
    return notBuilt('queue.start', jobIds)
  }

  /** Take no new jobs; running ones go on. */
  async function stop(): Promise<void> {
    return notBuilt('queue.stop')
  }

  async function pauseAll(): Promise<void> {
    return notBuilt('queue.pauseAll')
  }

  async function resumeAll(): Promise<void> {
    return notBuilt('queue.resumeAll')
  }

  async function cancelAll(): Promise<void> {
    return notBuilt('queue.cancelAll')
  }

  async function pause(jobId: string): Promise<void> {
    return notBuilt('queue.pause', jobId)
  }

  async function resume(jobId: string): Promise<void> {
    return notBuilt('queue.resume', jobId)
  }

  async function cancel(jobId: string): Promise<void> {
    return notBuilt('queue.cancel', jobId)
  }

  async function retry(jobId: string): Promise<void> {
    return notBuilt('queue.retry', jobId)
  }

  async function duplicate(jobId: string): Promise<void> {
    return notBuilt('queue.duplicate', jobId)
  }

  async function remove(jobId: string): Promise<void> {
    return notBuilt('queue.remove', jobId)
  }

  /** These jobs in this order (they take the places they had among themselves). */
  async function reorder(jobIds: string[]): Promise<void> {
    return notBuilt('queue.reorder', jobIds)
  }

  async function setWhenDone(value: WhenDone): Promise<void> {
    return notBuilt('queue.setWhenDone', value)
  }

  /** Cancels the running when-done countdown. */
  async function cancelPower(): Promise<void> {
    return notBuilt('queue.cancelPower')
  }

  /** `GET /api/queue/{id}/log` from byte `from`. */
  async function readLog(jobId: string, from?: number): Promise<JobLogChunk> {
    return notBuilt('queue.readLog', jobId, from)
  }

  /** Reads `GET /api/queue`, the when-done setting and `GET /api/power` again. */
  async function resync(): Promise<void> {
    return notBuilt('queue.resync')
  }

  function onJobState(event: EventOf<'job.state'>): void {
    notBuilt('queue.onJobState', event)
  }

  function onJobProgress(event: EventOf<'job.progress'>): void {
    notBuilt('queue.onJobProgress', event)
  }

  function onJobLog(event: EventOf<'job.log'>): void {
    notBuilt('queue.onJobLog', event)
  }

  function onQueueChanged(event: EventOf<'queue.changed'>): void {
    notBuilt('queue.onQueueChanged', event)
  }

  function onQueueProcessing(event: QueueProcessingEvent): void {
    notBuilt('queue.onQueueProcessing', event)
  }

  function onPowerCountdown(event: PowerCountdown): void {
    notBuilt('queue.onPowerCountdown', event)
  }

  return {
    jobs,
    processing,
    only,
    whenDone,
    power,
    logTicks,
    loaded,
    counts,
    overallProgress,
    byId,
    add,
    start,
    stop,
    pauseAll,
    resumeAll,
    cancelAll,
    pause,
    resume,
    cancel,
    retry,
    duplicate,
    remove,
    reorder,
    setWhenDone,
    cancelPower,
    readLog,
    resync,
    onJobState,
    onJobProgress,
    onJobLog,
    onQueueChanged,
    onQueueProcessing,
    onPowerCountdown,
  }
})
