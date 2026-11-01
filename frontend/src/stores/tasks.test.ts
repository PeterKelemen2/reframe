import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { configureClient } from '@/api/client'
import { type Deferred, deferred, FakeServer, settle } from '@/api/testing/fakes'
import type { TaskInfo } from '@/api/types'

import { KEEP_ENDED, TaskLostError, useTasksStore } from './tasks'

function task(id: string, state: TaskInfo['state'], extra: Partial<TaskInfo> = {}): TaskInfo {
  return { id, kind: 'probe_sources', state, ...extra }
}

describe('the tasks store', () => {
  let server: FakeServer
  let listed: TaskInfo[]
  let held: Deferred<void> | null

  beforeEach(() => {
    setActivePinia(createPinia())
    listed = []
    held = null
    server = new FakeServer().on('GET /api/tasks', async () => {
      const answer = structuredClone(listed)
      if (held !== null) await held.promise
      return answer
    })
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  })

  it('resolves a wait when the task ends, a failed one too', async () => {
    const tasks = useTasksStore()
    const waiting = tasks.wait('t1')
    tasks.onTaskProgress({ type: 'task.progress', task: task('t1', 'running', { progress: 50 }) })
    expect(tasks.tasks.t1?.progress).toBe(50)
    tasks.onTaskDone({ type: 'task.done', task: task('t1', 'failed', { error: 'no file' }) })
    expect(await waiting).toMatchObject({ state: 'failed', error: 'no file' })
  })

  it('resolves a wait at once for a task that has ended', async () => {
    const tasks = useTasksStore()
    tasks.onTaskDone({ type: 'task.done', task: task('t1', 'done', { result: 1 }) })
    expect(await tasks.wait('t1')).toMatchObject({ result: 1 })
  })

  it('resolves a wait from a read after a lost connection', async () => {
    const tasks = useTasksStore()
    tasks.onTaskProgress({ type: 'task.progress', task: task('t1', 'running') })
    const waiting = tasks.wait('t1')
    listed = [task('t1', 'done', { result: 'probed' })]
    await tasks.resync()
    expect(await waiting).toMatchObject({ state: 'done', result: 'probed' })
  })

  it('rejects a wait when a read sent after it does not list the task', async () => {
    const tasks = useTasksStore()
    const waiting = tasks.wait('t1')
    await tasks.resync()
    await expect(waiting).rejects.toBeInstanceOf(TaskLostError)
  })

  it('keeps a wait when a read sent before it does not list the task', async () => {
    const tasks = useTasksStore()
    held = deferred()
    const read = tasks.resync()
    await settle()
    let outcome = 'waiting'
    tasks.wait('t1').then(
      () => (outcome = 'resolved'),
      () => (outcome = 'rejected'),
    )
    held.resolve()
    await read
    await settle()
    expect(outcome).toBe('waiting')
    tasks.onTaskDone({ type: 'task.done', task: task('t1', 'done') })
    await settle()
    expect(outcome).toBe('resolved')
  })

  it('does not move an ended task back to running', async () => {
    const tasks = useTasksStore()
    listed = [task('t1', 'done')]
    held = deferred()
    const read = tasks.resync()
    await settle()
    // Sent before the task ended, it comes after the read was sent.
    tasks.onTaskProgress({ type: 'task.progress', task: task('t1', 'running', { progress: 90 }) })
    held.resolve()
    await read
    expect(tasks.tasks.t1?.state).toBe('done')
  })

  it('keeps a bounded number of ended tasks, the newest', () => {
    const tasks = useTasksStore()
    for (let i = 0; i < KEEP_ENDED + 5; i += 1) {
      tasks.onTaskDone({ type: 'task.done', task: task(`t${i}`, 'done') })
    }
    tasks.onTaskProgress({ type: 'task.progress', task: task('running', 'running') })
    const ids = Object.keys(tasks.tasks)
    expect(ids).toHaveLength(KEEP_ENDED + 1)
    expect(ids).not.toContain('t4')
    expect(ids).toContain('t5')
    expect(ids).toContain('running')
  })

  it('cancels a task on the server', async () => {
    server.on('POST /api/tasks/t1/cancel', { cancelled: true })
    await useTasksStore().cancel('t1')
    expect(server.count('POST /api/tasks/t1/cancel')).toBe(1)
  })
})
