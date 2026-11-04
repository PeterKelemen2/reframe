import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'

import { desktopBackend } from '@/api/boot'
import type { QueueJob } from '@/api/types'
import { platform } from '@/platform'
import type { DesktopShell } from '@/platform/types'
import { useQueueStore } from '@/stores/queue'

import { useQuitFlow } from './useQuitFlow'

let steps: string[]
let requestQuit: (() => void) | null
let tray: boolean

function fakeShell(): DesktopShell {
  return {
    onQuitRequested(cb) {
      requestQuit = cb
      return () => (requestQuit = null)
    },
    quitReady: vi.fn<() => Promise<void>>(async () => void steps.push('quitReady')),
    quit: vi.fn<() => Promise<void>>(async () => void steps.push('quit')),
    hideMainWindow: vi.fn<() => Promise<void>>(async () => void steps.push('hide')),
    settings: async () => ({ tray }),
  } as Partial<DesktopShell> as DesktopShell
}

function job(id: string, state: QueueJob['state']): QueueJob {
  return { id, state, settings: { source: { path: `/m/${id}.mkv` } } } as QueueJob
}

let scope = effectScope()

function start(jobs: QueueJob[], owned = true) {
  const queue = useQueueStore()
  queue.jobs = jobs
  queue.loaded = true
  vi.spyOn(queue, 'stop').mockImplementation(async () => void steps.push('stop'))
  vi.spyOn(queue, 'cancel').mockImplementation(async (id) => void steps.push(`cancel ${id}`))
  desktopBackend.value = {
    state: 'ready',
    info: {
      baseUrl: 'http://127.0.0.1:8731',
      token: 't',
      instance: 'i',
      owned,
      privateQueue: null,
    },
  }
  const flow = scope.run(() => useQuitFlow())!
  return { queue, flow }
}

async function close(): Promise<void> {
  requestQuit?.()
  await flushPromises()
}

beforeEach(() => {
  setActivePinia(createPinia())
  steps = []
  requestQuit = null
  tray = false
  platform.desktop = fakeShell()
  scope = effectScope()
})

afterEach(() => {
  scope.stop()
  platform.desktop = null
  desktopBackend.value = null
  vi.restoreAllMocks()
})

describe('the quit flow', () => {
  it('quits at once when no job runs', async () => {
    const { flow } = start([job('a', 'waiting'), job('b', 'done')])
    await close()
    expect(steps).toEqual(['quitReady', 'quit'])
    expect(flow.question.value).toBeNull()
  })

  it('asks when jobs run or are paused, counting another front end’s', async () => {
    tray = true
    const { flow } = start([job('a', 'running'), job('cli', 'paused'), job('c', 'waiting')])
    await close()
    expect(flow.question.value).toEqual({ active: 2, tray: true })
    expect(steps).toEqual(['quitReady'])
  })

  it('counts the jobs that still run while it asks', async () => {
    const { queue, flow } = start([job('a', 'running'), job('b', 'running')])
    await close()
    queue.jobs = [job('a', 'done'), job('b', 'running')]
    expect(flow.question.value).toEqual({ active: 1, tray: false })
  })

  it('stops the app’s own server with its jobs on Stop jobs and quit', async () => {
    const { flow } = start([job('a', 'running')], true)
    await close()
    await flow.answer('stop')
    expect(steps).toEqual(['quitReady', 'quit'])
    expect(flow.question.value).toBeNull()
  })

  it('cancels another owner’s running and paused jobs before it quits', async () => {
    const { flow } = start([job('a', 'running'), job('b', 'paused'), job('c', 'waiting')], false)
    await close()
    await flow.answer('stop')
    expect(steps).toEqual(['quitReady', 'stop', 'cancel a', 'cancel b', 'quit'])
  })

  it('does not quit when a cancel fails', async () => {
    const { queue, flow } = start([job('a', 'running')], false)
    vi.mocked(queue.cancel).mockRejectedValue(new Error('500'))
    await close()
    await expect(flow.answer('stop')).rejects.toThrow('500')
    expect(steps).not.toContain('quit')
  })

  it('hides the window on Keep running in tray, and does nothing on Cancel', async () => {
    tray = true
    const { flow } = start([job('a', 'running')])
    await close()
    await flow.answer('tray')
    await close()
    await flow.answer('cancel')
    expect(steps).toEqual(['quitReady', 'hide'])
    expect(flow.question.value).toBeNull()
  })

  it('says it can answer a close only once the queue is read', async () => {
    const queue = useQueueStore()
    scope.run(() => useQuitFlow())
    await flushPromises()
    expect(steps).toEqual([])
    queue.loaded = true
    await flushPromises()
    queue.loaded = false
    await flushPromises()
    queue.loaded = true
    await flushPromises()
    expect(steps).toEqual(['quitReady'])
  })

  it('quits without asking when the when-done quit runs', async () => {
    const { queue } = start([job('a', 'running')])
    const countdown = { type: 'power.countdown', countdown_id: 'p1', seconds_left: 0 } as const
    queue.onPowerCountdown({ ...countdown, action: 'quit', phase: 'tick' } as never)
    queue.onPowerCountdown({ ...countdown, action: 'sleep', phase: 'executing' } as never)
    await flushPromises()
    expect(steps).toEqual(['quitReady'])
    queue.onPowerCountdown({ ...countdown, action: 'quit', phase: 'executing' } as never)
    await flushPromises()
    expect(steps).toEqual(['quitReady', 'quit'])
  })

  it('stops listening when its component goes', async () => {
    start([])
    scope.stop()
    expect(requestQuit).toBeNull()
  })
})
