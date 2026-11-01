import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'

import { api, unwrap } from '@/api/client'
import { createMirror } from '@/api/mirror'
import type {
  EventOf,
  JobLogChunk,
  JobSettings,
  JobState,
  QueueJob,
  QueueProcessingEvent,
  Schemas,
  WhenDone,
} from '@/api/types'

import { useSettingsStore } from './settings'

export type PowerCountdown = EventOf<'power.countdown'>

type QueueEvent =
  | EventOf<'job.state'>
  | EventOf<'job.progress'>
  | EventOf<'queue.changed'>
  | EventOf<'power.countdown'>
  | QueueProcessingEvent

// The run state joins the snapshot together with the `queue.processing` event; until the
// generated schema has it, an older server sends neither and the copy keeps what it has.
type QueueSnapshot = Schemas['QueueSnapshot'] & { processing?: boolean; only?: string[] | null }

interface Snapshot {
  queue: QueueSnapshot
  power: Schemas['PowerState']
}

const ENDED = new Set<JobState>(['done', 'failed', 'cancelled', 'interrupted'])

/** A job of this client's add that no `queue.changed` has listed yet. */
interface Awaited {
  job: QueueJob
  /** The mirror's tick when the answer came: a read sent after it shows whether it is there. */
  answeredAt: number
}

/** Start taking waiting jobs; `jobIds`: only these. */
async function start(jobIds?: string[]): Promise<void> {
  const body = jobIds === undefined ? undefined : { job_ids: jobIds }
  unwrap(await api.POST('/api/queue/start', { body }))
}

/** Take no new jobs; running ones go on. */
async function stop(): Promise<void> {
  unwrap(await api.POST('/api/queue/stop'))
}

async function pauseAll(): Promise<void> {
  unwrap(await api.POST('/api/queue/pause'))
}

async function resumeAll(): Promise<void> {
  unwrap(await api.POST('/api/queue/resume'))
}

async function cancelAll(): Promise<void> {
  unwrap(await api.POST('/api/queue/cancel'))
}

function jobPath(jobId: string) {
  return { params: { path: { job_id: jobId } } }
}

async function pause(jobId: string): Promise<void> {
  unwrap(await api.POST('/api/queue/{job_id}/pause', jobPath(jobId)))
}

async function resume(jobId: string): Promise<void> {
  unwrap(await api.POST('/api/queue/{job_id}/resume', jobPath(jobId)))
}

async function cancel(jobId: string): Promise<void> {
  unwrap(await api.POST('/api/queue/{job_id}/cancel', jobPath(jobId)))
}

async function retry(jobId: string): Promise<void> {
  unwrap(await api.POST('/api/queue/{job_id}/retry', jobPath(jobId)))
}

async function remove(jobId: string): Promise<void> {
  unwrap(await api.DELETE('/api/queue/{job_id}', jobPath(jobId)))
}

/** Cancels the running when-done countdown. */
async function cancelPower(): Promise<void> {
  unwrap(await api.POST('/api/power/cancel'))
}

/** `GET /api/queue/{id}/log` from byte `from`. */
async function readLog(jobId: string, from?: number): Promise<JobLogChunk> {
  return unwrap(
    await api.GET('/api/queue/{job_id}/log', {
      params: { path: { job_id: jobId }, query: { from } },
    }),
  )
}

/** The server's queue, kept current by events and read again after a lost connection. */
export const useQueueStore = defineStore('queue', () => {
  const settingsStore = useSettingsStore()

  /** Every job, in queue order. Each change replaces the job's object. */
  const jobs = shallowRef<QueueJob[]>([])
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

  /** Queue order: the last `queue.changed`, or the last read. */
  let order: string[] = []
  /** What the copy knows of each job; a job that left the order stays until the next read. */
  let known = new Map<string, QueueJob>()
  const awaited = new Map<string, Awaited>()
  let adding = 0
  /** A `queue.changed` listed a job the copy has no data for while an add was under way. */
  let unknownDuringAdd = false

  watch(
    () => settingsStore.settings?.queue?.when_done,
    (value) => {
      if (value !== undefined) whenDone.value = value
    },
    { immediate: true, flush: 'sync' },
  )

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
  const overallProgress = computed<number | null>(() => {
    const active = jobs.value.filter((job) => job.state === 'running' || job.state === 'paused')
    if (active.length === 0) return null
    const percent = active.reduce((sum, job) => sum + (job.progress?.percent ?? 0), 0)
    return percent / active.length / 100
  })

  function rebuild(): void {
    const ids = [...order]
    for (const [jobId, entry] of awaited) {
      if (!ids.includes(jobId)) ids.splice(Math.min(entry.job.position, ids.length), 0, jobId)
    }
    const next: QueueJob[] = []
    for (const jobId of ids) {
      const job = known.get(jobId)
      if (job === undefined) continue
      next.push(job.position === next.length ? job : { ...job, position: next.length })
    }
    jobs.value = next
  }

  function change(jobId: string, patch: Partial<QueueJob>): void {
    const job = known.get(jobId)
    if (job === undefined) return
    known.set(jobId, { ...job, ...patch })
    const entry = awaited.get(jobId)
    if (entry !== undefined) awaited.set(jobId, { ...entry, job: { ...entry.job, ...patch } })
    rebuild()
  }

  function onState(event: EventOf<'job.state'>): void {
    const job = known.get(event.job_id)
    // No data yet: the read or the add answer that brings the job replays this event.
    if (job === undefined || event.previous == null) return
    // Applied only from the state it starts at, so an event older than a read changes nothing
    // and a run of transitions replayed on a read ends where the server is.
    if (job.state !== event.previous) return
    const patch: Partial<QueueJob> = { state: event.state, error: event.error ?? null }
    const now = new Date().toISOString()
    if (event.state === 'waiting') {
      Object.assign(patch, { started_at: null, finished_at: null, progress: null })
    } else if (event.state === 'running' && event.previous === 'waiting') {
      Object.assign(patch, { started_at: now, finished_at: null, progress: null })
    } else if (ENDED.has(event.state)) {
      patch.finished_at = now
    }
    change(event.job_id, patch)
    // A run's end, a failed start or a retry changes what the event does not carry (the
    // output, the issues, the times): a read brings it. A waiting job's cancel does not.
    const ends = ENDED.has(event.state) || ENDED.has(event.previous)
    if (ends && !(event.previous === 'waiting' && event.state === 'cancelled')) mirror.need()
  }

  function onProgress(event: EventOf<'job.progress'>): void {
    const job = known.get(event.job_id)
    if (job === undefined || (job.state !== 'running' && job.state !== 'paused')) return
    change(event.job_id, { progress: event.progress })
  }

  function onOrder(event: EventOf<'queue.changed'>): void {
    order = [...event.job_ids]
    for (const jobId of order) awaited.delete(jobId)
    rebuild()
    if (order.some((jobId) => !known.has(jobId))) {
      // Another front end's job; or this client's, whose add answer is still on its way.
      if (adding > 0) unknownDuringAdd = true
      else mirror.need()
    }
  }

  function onCountdown(event: PowerCountdown): void {
    if (event.phase === 'started' || event.phase === 'tick') power.value = event
    else if (power.value?.countdown_id === event.countdown_id) power.value = null
  }

  const mirror = createMirror<Snapshot, QueueEvent>({
    async fetch() {
      const [queue, pending] = await Promise.all([api.GET('/api/queue'), api.GET('/api/power')])
      return { queue: unwrap(queue) as QueueSnapshot, power: unwrap(pending) }
    },
    apply(snapshot, sentAt) {
      known = new Map(snapshot.queue.jobs.map((job) => [job.id, job]))
      order = snapshot.queue.jobs.map((job) => job.id)
      for (const [jobId, entry] of awaited) {
        if (known.has(jobId) || entry.answeredAt < sentAt) awaited.delete(jobId)
        else known.set(jobId, entry.job)
      }
      if (snapshot.queue.processing !== undefined) processing.value = snapshot.queue.processing
      if (snapshot.queue.only !== undefined) only.value = snapshot.queue.only
      power.value = snapshot.power.pending
      logTicks.value = Object.fromEntries(
        Object.entries(logTicks.value).filter(([jobId]) => known.has(jobId)),
      )
      loaded.value = true
      rebuild()
    },
    handle(event) {
      switch (event.type) {
        case 'job.state':
          onState(event)
          break
        case 'job.progress':
          onProgress(event)
          break
        case 'queue.changed':
          onOrder(event)
          break
        case 'power.countdown':
          onCountdown(event)
          break
        case 'queue.processing':
          processing.value = event.processing
          only.value = event.only
          break
      }
    },
  })

  /** Puts the jobs of an add's answer into the copy, then the events about them since. */
  function take(added: QueueJob[], since: readonly QueueEvent[]): void {
    const answeredAt = mirror.tick()
    const ids = new Set(added.map((job) => job.id))
    const listed = new Set(
      since.flatMap((event) => (event.type === 'queue.changed' ? event.job_ids : [])),
    )
    for (const job of added) {
      // A read brought it already (newer), or the events listed it and then removed it.
      if (known.has(job.id) || (listed.has(job.id) && !order.includes(job.id))) continue
      known.set(job.id, job)
      if (!order.includes(job.id)) awaited.set(job.id, { job, answeredAt })
    }
    rebuild()
    mirror.replay(
      since.filter(
        (event) =>
          (event.type === 'job.state' || event.type === 'job.progress') && ids.has(event.job_id),
      ),
    )
  }

  async function adds<T>(request: () => Promise<T>, jobsOf: (answer: T) => QueueJob[]): Promise<T> {
    adding += 1
    let done = false
    try {
      return await mirror.track(request, (answer, since) => {
        adding -= 1
        done = true
        take(jobsOf(answer), since)
      })
    } finally {
      if (!done) adding -= 1
      if (adding === 0 && unknownDuringAdd) {
        unknownDuringAdd = false
        if (order.some((jobId) => !known.has(jobId)) && !mirror.reading) {
          mirror.read().catch((error: unknown) => console.error(error))
        }
      }
    }
  }

  function byId(id: string): QueueJob | undefined {
    return jobs.value.find((job) => job.id === id)
  }

  /** Adds jobs at the end of the queue (never attached); `start` also starts the queue. */
  async function add(settings: JobSettings[], options?: { start?: boolean }): Promise<QueueJob[]> {
    const added = await adds(
      async () => unwrap(await api.POST('/api/queue', { body: { jobs: settings } })),
      (answer) => answer,
    )
    if (options?.start) await start()
    return added
  }

  async function duplicate(jobId: string): Promise<void> {
    await adds(
      async () => unwrap(await api.POST('/api/queue/{job_id}/duplicate', jobPath(jobId))),
      (answer) => [answer],
    )
  }

  /**
   * These jobs in this order (they take the places they had among themselves). The copy shows
   * the order at once, so a dragged row does not jump back while the request is under way.
   */
  async function reorder(jobIds: string[]): Promise<void> {
    const moved = new Set(jobIds)
    const queued = [...jobIds]
    order = order.map((jobId) => (moved.has(jobId) ? (queued.shift() ?? jobId) : jobId))
    rebuild()
    try {
      unwrap(await api.PUT('/api/queue/order', { body: { job_ids: jobIds } }))
    } catch (error) {
      void resync().catch(() => undefined)
      throw error
    }
  }

  async function setWhenDone(value: WhenDone): Promise<void> {
    const answer = unwrap(await api.PUT('/api/queue/when-done', { body: { when_done: value } }))
    whenDone.value = answer.when_done
    const queue = settingsStore.settings?.queue
    if (queue !== undefined) queue.when_done = answer.when_done
  }

  /** Reads `GET /api/queue`, the when-done setting and `GET /api/power` again. */
  async function resync(): Promise<void> {
    await Promise.all([mirror.read(), settingsStore.load()])
  }

  function onJobState(event: EventOf<'job.state'>): void {
    mirror.event(event)
  }

  function onJobProgress(event: EventOf<'job.progress'>): void {
    mirror.event(event)
  }

  function onJobLog(event: EventOf<'job.log'>): void {
    logTicks.value[event.job_id] = (logTicks.value[event.job_id] ?? 0) + 1
  }

  function onQueueChanged(event: EventOf<'queue.changed'>): void {
    mirror.event(event)
  }

  function onQueueProcessing(event: QueueProcessingEvent): void {
    mirror.event(event)
  }

  function onPowerCountdown(event: PowerCountdown): void {
    mirror.event(event)
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
