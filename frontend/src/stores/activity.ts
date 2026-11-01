import { defineStore } from 'pinia'
import { shallowRef, triggerRef } from 'vue'

import type { QueueJob, QueueProcessingEvent, ReframeEvent } from '@/api/types'

import { useQueueStore } from './queue'

/** What a `queue.changed` changed against the order before it. */
export interface OrderChange {
  /** Jobs that left the queue. */
  removed: string[]
  /** The jobs that stayed are in another order. */
  moved: boolean
}

export interface ActivityEntry {
  /** Unique in this session, for list keys. */
  id: number
  /** When the event arrived. */
  at: Date
  event: ReframeEvent | QueueProcessingEvent
  /** Set for a `queue.changed` that removed or moved jobs. */
  change?: OrderChange
}

/** The log keeps this many entries; older ones are dropped. */
export const MAX_ENTRIES = 1000

/**
 * The key of an event that comes several times a second while something runs (progress, log
 * lines, a countdown's ticks) or with every add (an order that only grew); `null` for others.
 * The log keeps only the latest event of each key, so a long encode does not push the readable
 * entries out.
 */
function streamKey(
  event: ReframeEvent | QueueProcessingEvent,
  change?: OrderChange,
): string | null {
  switch (event.type) {
    case 'job.progress':
    case 'job.log':
      return `${event.type}:${event.job_id}`
    case 'task.progress':
      return `${event.type}:${event.task.id}`
    case 'power.countdown':
      return event.phase === 'tick' ? `tick:${event.countdown_id}` : null
    case 'queue.changed':
      return change === undefined ? event.type : null
    default:
      return null
  }
}

function sourceName(job: QueueJob): string {
  const path = job.settings.source.path
  return path.split(/[/\\]/).findLast((part) => part !== '') ?? path
}

/** The global activity log: the events of this session, newest last, bounded. */
export const useActivityStore = defineStore('activity', () => {
  const queue = useQueueStore()
  const entries = shallowRef<ActivityEntry[]>([])
  let next = 1
  /** The order of the last `queue.changed`; `null` until the first. */
  let lastOrder: string[] | null = null
  /** The source file name of every job seen, so that a removed job keeps its name. */
  const names = new Map<string, string>()
  /** The entry of each stream key. */
  const streams = new Map<string, ActivityEntry>()

  function remember(jobId: string): void {
    const job = queue.byId(jobId)
    if (job !== undefined) names.set(jobId, sourceName(job))
  }

  function orderChange(jobIds: string[]): OrderChange | undefined {
    const before = lastOrder ?? queue.jobs.map((job) => job.id)
    lastOrder = [...jobIds]
    const now = new Set(jobIds)
    const removed = before.filter((jobId) => !now.has(jobId))
    const was = new Set(before)
    const kept = jobIds.filter((jobId) => was.has(jobId))
    const keptBefore = before.filter((jobId) => now.has(jobId))
    const moved = kept.some((jobId, index) => keptBefore[index] !== jobId)
    return removed.length > 0 || moved ? { removed, moved } : undefined
  }

  /**
   * The event dispatcher calls it for every event, before the stores handle it: a job that an
   * event removes is still in the queue store here.
   */
  function record(event: ReframeEvent | QueueProcessingEvent): void {
    let change: OrderChange | undefined
    if (event.type === 'queue.changed') {
      for (const job of queue.jobs) remember(job.id)
      change = orderChange(event.job_ids)
    } else if ('job_id' in event && typeof event.job_id === 'string') {
      remember(event.job_id)
    }
    const entry: ActivityEntry = { id: next++, at: new Date(), event }
    if (change !== undefined) entry.change = change
    const list = entries.value
    const key = streamKey(event, change)
    if (key !== null) {
      const before = streams.get(key)
      const index = before === undefined ? -1 : list.indexOf(before)
      if (index >= 0) list.splice(index, 1)
      streams.set(key, entry)
    }
    list.push(entry)
    if (list.length > MAX_ENTRIES) {
      for (const dropped of list.splice(0, list.length - MAX_ENTRIES)) forget(dropped)
    }
    triggerRef(entries)
  }

  function forget(entry: ActivityEntry): void {
    for (const [key, kept] of streams) if (kept === entry) streams.delete(key)
  }

  /** The job's source file name: from the queue, or remembered after it left; `null` if never seen. */
  function jobName(jobId: string): string | null {
    const job = queue.byId(jobId)
    if (job !== undefined) return sourceName(job)
    return names.get(jobId) ?? null
  }

  function clear(): void {
    entries.value = []
    streams.clear()
  }

  return { entries, record, clear, jobName }
})
