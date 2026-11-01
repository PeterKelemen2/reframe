import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { EventOf, JobState } from '@/api/types'
import { job, queueDouble, resetQueue } from '@/components/queue/testing'

import { MAX_ENTRIES, useActivityStore } from './activity'

const queue = queueDouble()
vi.mock('./queue', () => ({ useQueueStore: () => queue }))

function state(job_id: string, previous: JobState | null, next: JobState): EventOf<'job.state'> {
  return { type: 'job.state', job_id, previous, state: next }
}

function order(...job_ids: string[]): EventOf<'queue.changed'> {
  return { type: 'queue.changed', job_ids }
}

const progress = (job_id: string, percent: number): EventOf<'job.progress'> => ({
  type: 'job.progress',
  job_id,
  progress: { percent, step: 0, step_count: 1 },
})
const log = (job_id: string, line: string): EventOf<'job.log'> => ({
  type: 'job.log',
  job_id,
  lines: [line],
  dropped: 0,
})
const tick = (seconds_left: number): EventOf<'power.countdown'> => ({
  type: 'power.countdown',
  countdown_id: 'p',
  action: 'sleep',
  phase: 'tick',
  seconds_left,
})
const probe = (percent: number): EventOf<'task.progress'> => ({
  type: 'task.progress',
  task: { id: 't', kind: 'probe_sources', state: 'running', progress: percent },
})

beforeEach(() => {
  setActivePinia(createPinia())
  resetQueue(queue)
})

describe('the activity log', () => {
  it('keeps each readable event with the time it came', () => {
    const activity = useActivityStore()
    const before = Date.now()
    activity.record(state('a', 'waiting', 'running'))
    expect(activity.entries).toHaveLength(1)
    expect(activity.entries[0]?.event).toEqual(state('a', 'waiting', 'running'))
    expect(activity.entries[0]?.at.getTime()).toBeGreaterThanOrEqual(before)
  })

  it('keeps only the latest progress, log and tick event of each job, task and countdown', () => {
    const activity = useActivityStore()
    activity.record(state('a', 'waiting', 'running'))
    for (let n = 1; n <= 50; n++) {
      activity.record(progress('a', n))
      activity.record(progress('b', n))
      activity.record(log('a', `line ${n}`))
      activity.record(tick(60 - n))
      activity.record(probe(n))
    }
    activity.record({ ...tick(0), phase: 'cancelled' })
    activity.record(state('a', 'running', 'done'))
    expect(activity.entries.map((entry) => entry.event)).toEqual([
      state('a', 'waiting', 'running'),
      progress('a', 50),
      progress('b', 50),
      log('a', 'line 50'),
      tick(10),
      probe(50),
      { ...tick(0), phase: 'cancelled' },
      state('a', 'running', 'done'),
    ])
  })

  it(`keeps the newest ${MAX_ENTRIES} entries`, () => {
    const activity = useActivityStore()
    for (let n = 0; n < MAX_ENTRIES + 5; n++) activity.record(state(`j${n}`, 'waiting', 'running'))
    expect(activity.entries).toHaveLength(MAX_ENTRIES)
    const ids = activity.entries.map((entry) => (entry.event as EventOf<'job.state'>).job_id)
    expect(ids[0]).toBe('j5')
    expect(ids.at(-1)).toBe(`j${MAX_ENTRIES + 4}`)
  })

  it('records a removal with the name the job had, and keeps it after the job left', () => {
    const activity = useActivityStore()
    queue.jobs = [job('a'), job('b')]
    activity.record(order('a', 'b'))
    // The dispatcher records before the queue store applies the event: the job is still there.
    activity.record(order('b'))
    queue.jobs = [job('b')]
    const removal = activity.entries.at(-1)
    expect(removal?.change).toEqual({ removed: ['a'], moved: false })
    expect(activity.jobName('a')).toBe('a.mkv')
  })

  it('records a change of order, and only the latest of the orders that only grew', () => {
    const activity = useActivityStore()
    queue.jobs = [job('a'), job('b')]
    activity.record(order('a', 'b', 'c'))
    activity.record(order('a', 'b', 'c', 'd'))
    activity.record(order('b', 'a', 'c', 'd'))
    expect(activity.entries.map((entry) => [entry.event, entry.change])).toEqual([
      [order('a', 'b', 'c', 'd'), undefined],
      [order('b', 'a', 'c', 'd'), { removed: [], moved: true }],
    ])
  })

  it('compares the first order with the jobs the queue store holds', () => {
    const activity = useActivityStore()
    queue.jobs = [job('a'), job('b')]
    activity.record(order('b', 'a'))
    expect(activity.entries.map((entry) => entry.change)).toEqual([{ removed: [], moved: true }])
  })

  it('names a job from the queue, else from what it remembered, else not at all', () => {
    const activity = useActivityStore()
    queue.jobs = [job('a')]
    activity.record(state('a', 'waiting', 'running'))
    queue.jobs = [job('b')]
    expect(activity.jobName('b')).toBe('b.mkv')
    expect(activity.jobName('a')).toBe('a.mkv')
    expect(activity.jobName('never')).toBeNull()
  })

  it('clears every entry', () => {
    const activity = useActivityStore()
    activity.record(state('a', 'waiting', 'running'))
    activity.clear()
    expect(activity.entries).toEqual([])
  })
})
