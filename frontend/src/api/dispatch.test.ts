import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { platform } from '@/platform'
import { useActivityStore } from '@/stores/activity'
import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'
import { useTasksStore } from '@/stores/tasks'
import { useToastStore } from '@/stores/toasts'

import { dispatch } from './dispatch'
import type { AnyEvent } from './events'

const task = { id: 't', kind: 'probe_sources', state: 'running' } as const
const EVENTS: [AnyEvent, 'system' | 'tasks' | 'queue', string][] = [
  [{ type: 'capabilities.changed', encoders: [] }, 'system', 'onCapabilitiesChanged'],
  [{ type: 'tools.changed', tools: {} as never }, 'system', 'onToolsChanged'],
  [{ type: 'app.warning', code: 'c', message: 'm' }, 'system', 'onAppWarning'],
  [{ type: 'task.progress', task }, 'tasks', 'onTaskProgress'],
  [{ type: 'task.done', task: { ...task, state: 'done' } }, 'tasks', 'onTaskDone'],
  [
    { type: 'job.state', job_id: 'j', state: 'running', previous: 'waiting' },
    'queue',
    'onJobState',
  ],
  [
    { type: 'job.progress', job_id: 'j', progress: { percent: 1, step: 0, step_count: 1 } },
    'queue',
    'onJobProgress',
  ],
  [{ type: 'job.log', job_id: 'j', lines: [], dropped: 0 }, 'queue', 'onJobLog'],
  [{ type: 'queue.changed', job_ids: [] }, 'queue', 'onQueueChanged'],
  [
    { type: 'queue.processing', processing: true, only: null, reason: 'start' },
    'queue',
    'onQueueProcessing',
  ],
  [
    { type: 'power.countdown', countdown_id: 'c', action: 'sleep', phase: 'tick', seconds_left: 3 },
    'queue',
    'onPowerCountdown',
  ],
]

function stores() {
  return { system: useSystemStore(), tasks: useTasksStore(), queue: useQueueStore() }
}

describe('dispatch', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it.each(EVENTS)('hands %o to its store and records it', (event, store, handler) => {
    const target = stores()[store] as unknown as Record<string, () => void>
    const spy = vi.spyOn(target, handler).mockImplementation(() => undefined)
    dispatch(event)
    expect(spy).toHaveBeenCalledWith(event)
    expect(useActivityStore().entries.map((entry) => entry.event)).toEqual([event])
  })

  it('goes on after a handler that throws', () => {
    const { queue } = stores()
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.spyOn(queue, 'onJobState').mockImplementation(() => {
      throw new Error('broken')
    })
    const progress = vi.spyOn(queue, 'onJobProgress').mockImplementation(() => undefined)
    const [stateEvent] = EVENTS.find(([event]) => event.type === 'job.state') ?? []
    const [progressEvent] = EVENTS.find(([event]) => event.type === 'job.progress') ?? []
    dispatch(stateEvent as AnyEvent)
    dispatch(progressEvent as AnyEvent)
    expect(progress).toHaveBeenCalled()
    expect(useActivityStore().entries).toHaveLength(2)
  })

  it('reads every snapshot again on a resync event', () => {
    const resyncs = Object.values(stores()).map((store) =>
      vi.spyOn(store, 'resync').mockResolvedValue(undefined),
    )
    dispatch({ type: 'resync', reason: 'overflow', dropped: 0 })
    for (const resync of resyncs) expect(resync).toHaveBeenCalledTimes(1)
  })

  it('shows a notification as a toast, and as a system notification while the page is hidden', () => {
    const notify = vi.spyOn(platform, 'notify').mockResolvedValue(undefined)
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    dispatch({ type: 'notification', title: 'Job done', message: 'a.mkv', level: 'success' })
    expect(useToastStore().items).toEqual([
      expect.objectContaining({ severity: 'success', summary: 'Job done', detail: 'a.mkv' }),
    ])
    expect(notify).not.toHaveBeenCalled()

    hidden.mockReturnValue(true)
    dispatch({ type: 'notification', title: 'Job failed', message: '', level: 'warning' })
    expect(useToastStore().items[1]).toMatchObject({ severity: 'warn', summary: 'Job failed' })
    expect(notify).toHaveBeenCalledWith('Job failed', '')
  })

  it('records an event of a type it does not know, and does nothing else', () => {
    const event = { type: 'job.paused_by_ufo' } as unknown as AnyEvent
    expect(() => dispatch(event)).not.toThrow()
    expect(useActivityStore().entries).toHaveLength(1)
  })
})
