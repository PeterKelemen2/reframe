import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { configureClient } from '@/api/client'
import {
  type Deferred,
  deferred,
  FakeServer,
  problem,
  type Recorded,
  settle,
} from '@/api/testing/fakes'
import type { EventOf, JobSettings, JobState, QueueJob } from '@/api/types'

import { useQueueStore } from './queue'
import { useSettingsStore } from './settings'

function job(id: string, jobState: JobState = 'waiting', extra: Partial<QueueJob> = {}): QueueJob {
  return {
    id,
    position: 0,
    state: jobState,
    settings: { source: { path: `/media/${id}.mkv` } } as unknown as JobSettings,
    issues: [],
    created_at: '2026-10-29T10:00:00Z',
    ...extra,
  } as QueueJob
}

function state(job_id: string, previous: JobState | null, next: JobState): EventOf<'job.state'> {
  return { type: 'job.state', job_id, previous, state: next }
}

function order(...job_ids: string[]): EventOf<'queue.changed'> {
  return { type: 'queue.changed', job_ids }
}

function progress(job_id: string, percent: number): EventOf<'job.progress'> {
  return { type: 'job.progress', job_id, progress: { percent, step: 0, step_count: 1 } }
}

function countdown(
  countdown_id: string,
  phase: EventOf<'power.countdown'>['phase'],
): EventOf<'power.countdown'> {
  return { type: 'power.countdown', countdown_id, action: 'sleep', phase, seconds_left: 5 }
}

describe('the queue store', () => {
  let server: FakeServer
  let jobs: QueueJob[]
  /** When set, `GET /api/queue` waits for it. */
  let held: Deferred<void> | null

  beforeEach(() => {
    setActivePinia(createPinia())
    jobs = []
    held = null
    server = new FakeServer()
      .on('GET /api/queue', async () => {
        const answer = { jobs: structuredClone(jobs) }
        if (held !== null) await held.promise
        return answer
      })
      .on('GET /api/power', { pending: null })
      .on('GET /api/settings', { schema_version: 1, queue: { when_done: 'notify' } })
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  })

  async function loaded(...initial: QueueJob[]) {
    jobs = initial
    const queue = useQueueStore()
    await queue.resync()
    return queue
  }

  it('fills the jobs, the run state, the countdown and when-done from the snapshots', async () => {
    const pending = countdown('c1', 'tick')
    server.on('GET /api/power', { pending })
    server.on('GET /api/queue', {
      jobs: [job('a'), job('b', 'running')],
      processing: true,
      only: ['b'],
    })
    const queue = useQueueStore()
    expect(queue.loaded).toBe(false)
    await queue.resync()

    expect(queue.loaded).toBe(true)
    expect(queue.jobs.map((j) => [j.id, j.state, j.position])).toEqual([
      ['a', 'waiting', 0],
      ['b', 'running', 1],
    ])
    expect(queue.processing).toBe(true)
    expect(queue.only).toEqual(['b'])
    expect(queue.power).toEqual(pending)
    expect(queue.whenDone).toBe('notify')
  })

  it('keeps the run state when a snapshot does not carry it', async () => {
    const queue = await loaded(job('a'))
    queue.onQueueProcessing({
      type: 'queue.processing',
      processing: true,
      only: null,
      reason: 'start',
    })
    await queue.resync()
    expect(queue.processing).toBe(true)
  })

  it('applies a job state only from the state the event starts at', async () => {
    const queue = await loaded(job('a', 'paused'))
    // Older than the snapshot: the job ran and was paused since.
    queue.onJobState(state('a', 'waiting', 'running'))
    expect(queue.byId('a')?.state).toBe('paused')

    queue.onJobState(state('a', 'paused', 'running'))
    expect(queue.byId('a')?.state).toBe('running')
  })

  it('ignores the add event of a job it has', async () => {
    const queue = await loaded(job('a', 'failed', { error: 'The job has errors' }))
    queue.onJobState(state('a', null, 'failed'))
    expect(queue.byId('a')).toMatchObject({ state: 'failed', error: 'The job has errors' })
  })

  it('reads the queue after a run ends, and not after a waiting job is cancelled', async () => {
    const queue = await loaded(job('a', 'running'), job('b'))
    const reads = server.count('GET /api/queue')

    queue.onJobState(state('b', 'waiting', 'cancelled'))
    await settle()
    expect(server.count('GET /api/queue')).toBe(reads)
    expect(queue.byId('b')?.state).toBe('cancelled')
    expect(queue.byId('b')?.finished_at).toBeTruthy()

    jobs = [job('a', 'done', { output_path: '/out/a.mkv' }), job('b', 'cancelled')]
    queue.onJobState(state('a', 'running', 'done'))
    expect(queue.byId('a')?.state).toBe('done')
    await settle()
    expect(server.count('GET /api/queue')).toBe(reads + 1)
    expect(queue.byId('a')?.output_path).toBe('/out/a.mkv')
  })

  it('reads the queue after a retry, which changes the issues', async () => {
    const queue = await loaded(job('a', 'failed', { error: 'boom' }))
    const reads = server.count('GET /api/queue')
    jobs = [job('a')]
    queue.onJobState(state('a', 'failed', 'waiting'))
    expect(queue.byId('a')).toMatchObject({ state: 'waiting', error: null, finished_at: null })
    await settle()
    expect(server.count('GET /api/queue')).toBe(reads + 1)
  })

  it('applies an event that came during a read on top of the older answer', async () => {
    const queue = await loaded(job('a'))
    held = deferred()
    const read = queue.resync()
    await settle()
    queue.onJobState(state('a', 'waiting', 'running'))
    queue.onJobProgress(progress('a', 12))
    held.resolve()
    await read

    expect(queue.byId('a')).toMatchObject({ state: 'running', progress: { percent: 12 } })
  })

  it('applies progress to a running or paused job only', async () => {
    const queue = await loaded(job('a', 'running'), job('b', 'paused'), job('c', 'done'))
    queue.onJobProgress(progress('a', 40))
    queue.onJobProgress(progress('b', 50))
    queue.onJobProgress(progress('c', 10))
    expect(queue.byId('a')?.progress?.percent).toBe(40)
    expect(queue.byId('b')?.progress?.percent).toBe(50)
    expect(queue.byId('c')?.progress).toBeUndefined()
  })

  it('takes the order from queue.changed and drops the jobs it leaves out', async () => {
    const queue = await loaded(job('a'), job('b'), job('c'))
    queue.onQueueChanged(order('c', 'a'))
    expect(queue.jobs.map((j) => [j.id, j.position])).toEqual([
      ['c', 0],
      ['a', 1],
    ])
  })

  it('reads the queue for a job that another front end added', async () => {
    const queue = await loaded(job('a'))
    jobs = [job('a'), job('x')]
    queue.onJobState(state('x', null, 'waiting'))
    queue.onQueueChanged(order('a', 'x'))
    await settle()
    expect(queue.jobs.map((j) => j.id)).toEqual(['a', 'x'])
  })

  describe('add', () => {
    it('puts the answer at the end without a read, and never attaches', async () => {
      const queue = await loaded(job('a'))
      const reads = server.count('GET /api/queue')
      const answer = deferred<QueueJob[]>()
      server.on('POST /api/queue', () => answer.promise)
      const settings = { source: { path: '/media/n.mkv' } } as unknown as JobSettings

      const adding = queue.add([settings])
      await settle()
      // The events of the add come before its answer.
      queue.onJobState(state('n', null, 'waiting'))
      queue.onQueueChanged(order('a', 'n'))
      answer.resolve([job('n', 'waiting', { position: 1 })])
      const added = await adding
      await settle()

      expect(added.map((j) => j.id)).toEqual(['n'])
      expect(queue.jobs.map((j) => j.id)).toEqual(['a', 'n'])
      expect(server.count('GET /api/queue')).toBe(reads)
      const body = server.requests.find((r) => r.method === 'POST')?.body
      expect(body).toEqual({ jobs: [settings] })
    })

    it('keeps a job it added while an older queue.changed leaves it out', async () => {
      const queue = await loaded(job('a'), job('b'))
      server.on('POST /api/queue', [job('n', 'waiting', { position: 2 })])
      await queue.add([{} as JobSettings])
      // Sent before the add (a reorder by another front end), it comes after the answer.
      queue.onQueueChanged(order('b', 'a'))
      expect(queue.jobs.map((j) => j.id)).toEqual(['b', 'a', 'n'])

      queue.onQueueChanged(order('b', 'a', 'n'))
      queue.onQueueChanged(order('b', 'a'))
      expect(queue.jobs.map((j) => j.id)).toEqual(['b', 'a'])
    })

    it('leaves out a job that the events listed and removed before the answer', async () => {
      const queue = await loaded(job('a'))
      const answer = deferred<QueueJob[]>()
      server.on('POST /api/queue', () => answer.promise)
      const adding = queue.add([{} as JobSettings])
      await settle()
      queue.onQueueChanged(order('a', 'n'))
      queue.onQueueChanged(order('a'))
      answer.resolve([job('n', 'waiting', { position: 1 })])
      await adding
      await settle()
      expect(queue.jobs.map((j) => j.id)).toEqual(['a'])
    })

    it('applies the events of the new job that came before the answer', async () => {
      const queue = await loaded()
      const answer = deferred<QueueJob[]>()
      server.on('POST /api/queue', () => answer.promise)
      const adding = queue.add([{} as JobSettings], { start: false })
      await settle()
      queue.onJobState(state('n', null, 'waiting'))
      queue.onQueueChanged(order('n'))
      queue.onJobState(state('n', 'waiting', 'running'))
      queue.onJobProgress(progress('n', 5))
      answer.resolve([job('n')])
      await adding
      expect(queue.byId('n')).toMatchObject({ state: 'running', progress: { percent: 5 } })
    })

    it('reads after the add when another front end added a job meanwhile', async () => {
      const queue = await loaded()
      const answer = deferred<QueueJob[]>()
      server.on('POST /api/queue', () => answer.promise)
      const adding = queue.add([{} as JobSettings])
      await settle()
      jobs = [job('x'), job('n')]
      queue.onQueueChanged(order('x'))
      queue.onQueueChanged(order('x', 'n'))
      await settle()
      const reads = server.count('GET /api/queue')
      answer.resolve([job('n', 'waiting', { position: 1 })])
      await adding
      await settle()
      expect(server.count('GET /api/queue')).toBe(reads + 1)
      expect(queue.jobs.map((j) => j.id)).toEqual(['x', 'n'])
    })

    it('starts the queue after the add when asked', async () => {
      const queue = await loaded()
      server.on('POST /api/queue', [job('n')])
      server.on('POST /api/queue/start', () => new Response(null, { status: 204 }))
      await queue.add([{} as JobSettings], { start: true })
      const sent = server.requests.map((r) => `${r.method} ${r.path}`)
      expect(sent.slice(-2)).toEqual(['POST /api/queue', 'POST /api/queue/start'])
      expect(server.requests.at(-1)?.body).toBeUndefined()
    })

    it('drops a job it added when a read sent after the answer does not have it', async () => {
      const queue = await loaded(job('a'))
      server.on('POST /api/queue', [job('n', 'waiting', { position: 1 })])
      await queue.add([{} as JobSettings])
      expect(queue.jobs.map((j) => j.id)).toEqual(['a', 'n'])
      await queue.resync()
      expect(queue.jobs.map((j) => j.id)).toEqual(['a'])
    })

    it('keeps a job it added when a read sent before the answer does not have it', async () => {
      const queue = await loaded(job('a'))
      held = deferred()
      const read = queue.resync()
      await settle()
      server.on('POST /api/queue', [job('n', 'waiting', { position: 1 })])
      await queue.add([{} as JobSettings])
      held.resolve()
      await read
      expect(queue.jobs.map((j) => j.id)).toEqual(['a', 'n'])
    })

    it('adds a duplicate the same way, after its original', async () => {
      const queue = await loaded(job('a'), job('b'))
      server.on('POST /api/queue/a/duplicate', job('a2', 'waiting', { position: 1 }))
      await queue.duplicate('a')
      expect(queue.jobs.map((j) => j.id)).toEqual(['a', 'a2', 'b'])
    })

    it('replaces a failed job with its fixed settings at its place', async () => {
      const failed = job('b', 'failed', {
        position: 1,
        settings: {
          source: { path: '/media/b.mkv' },
          video: { encoder: 'hevc_nvenc' },
        } as unknown as JobSettings,
      })
      const queue = await loaded(job('a'), failed, job('c', 'waiting', { position: 2 }))
      server.on('POST /api/queue', [job('b2', 'waiting', { position: 1 })])
      server.on('DELETE /api/queue/b', () => new Response(null, { status: 204 }))
      await queue.retryWith('b', {
        label: 'Use libx265 (closest match)',
        patch: [{ op: 'replace', path: '/video/encoder', value: 'libx265' }],
        target: 'job',
      })
      const [added, removed] = server.requests.filter((r) => r.method !== 'GET')
      expect(`${added?.method} ${added?.path}`).toBe('POST /api/queue')
      expect(added?.body).toEqual({
        jobs: [{ source: { path: '/media/b.mkv' }, video: { encoder: 'libx265' } }],
        position: 1,
      })
      expect(`${removed?.method} ${removed?.path}`).toBe('DELETE /api/queue/b')
      expect(queue.byId('b2')?.state).toBe('waiting')
    })
  })

  it('follows the when-done countdown by its id', async () => {
    const queue = await loaded()
    queue.onPowerCountdown(countdown('c1', 'started'))
    queue.onPowerCountdown(countdown('c1', 'tick'))
    expect(queue.power?.phase).toBe('tick')
    queue.onPowerCountdown(countdown('c0', 'cancelled'))
    expect(queue.power?.countdown_id).toBe('c1')
    queue.onPowerCountdown(countdown('c1', 'cancelled'))
    expect(queue.power).toBeNull()
    queue.onPowerCountdown(countdown('c2', 'started'))
    queue.onPowerCountdown(countdown('c2', 'executing'))
    expect(queue.power).toBeNull()
  })

  it('takes the run state from queue.processing', async () => {
    const queue = await loaded()
    queue.onQueueProcessing({
      type: 'queue.processing',
      processing: true,
      only: ['a'],
      reason: 'start',
    })
    expect([queue.processing, queue.only]).toEqual([true, ['a']])
    queue.onQueueProcessing({
      type: 'queue.processing',
      processing: false,
      only: null,
      reason: 'stop',
    })
    expect([queue.processing, queue.only]).toEqual([false, null])
  })

  it('counts the log events of each job', async () => {
    const queue = await loaded(job('a', 'running'))
    const log: EventOf<'job.log'> = { type: 'job.log', job_id: 'a', lines: ['x'], dropped: 0 }
    queue.onJobLog(log)
    queue.onJobLog(log)
    expect(queue.logTicks).toEqual({ a: 2 })
  })

  it('gives the overall progress of the running and paused jobs', async () => {
    const queue = await loaded(job('a', 'running'), job('b', 'paused'), job('c', 'done'))
    queue.onJobProgress(progress('a', 40))
    queue.onJobProgress(progress('b', 80))
    expect(queue.overallProgress).toBeCloseTo(0.6)
    queue.onQueueChanged(order('c'))
    expect(queue.overallProgress).toBeNull()
  })

  it('shows a new order at once, and reads the queue again when the server refuses it', async () => {
    const queue = await loaded(job('a'), job('b'), job('c'))
    const answer = deferred<Response>()
    server.on('PUT /api/queue/order', () => answer.promise)
    const reordering = queue.reorder(['c', 'a'])
    expect(queue.jobs.map((j) => j.id)).toEqual(['c', 'b', 'a'])
    answer.resolve(problem(409, 'queue.unknown_job', 'No job c'))
    await expect(reordering).rejects.toThrow('No job c')
    await settle()
    expect(queue.jobs.map((j) => j.id)).toEqual(['a', 'b', 'c'])
    expect(server.requests.find((r) => r.method === 'PUT')?.body).toEqual({ job_ids: ['c', 'a'] })
  })

  it('sets when-done on the server and in the settings', async () => {
    const queue = await loaded()
    const settings = useSettingsStore()
    server.on('PUT /api/queue/when-done', (request: Recorded) => request.body)
    await queue.setWhenDone('sleep')
    expect(queue.whenDone).toBe('sleep')
    expect(settings.settings?.queue?.when_done).toBe('sleep')
    expect(server.requests.at(-1)?.body).toEqual({ when_done: 'sleep' })
  })

  it.each([
    ['start', (q: Q) => q.start(), 'POST /api/queue/start', undefined],
    [
      'start some',
      (q: Q) => q.start(['a']),
      'POST /api/queue/start',
      { job_ids: ['a'], own_batch: false },
    ],
    ['stop', (q: Q) => q.stop(), 'POST /api/queue/stop', undefined],
    ['pause all', (q: Q) => q.pauseAll(), 'POST /api/queue/pause', undefined],
    ['resume all', (q: Q) => q.resumeAll(), 'POST /api/queue/resume', undefined],
    ['cancel all', (q: Q) => q.cancelAll(), 'POST /api/queue/cancel', undefined],
    ['pause', (q: Q) => q.pause('a'), 'POST /api/queue/a/pause', undefined],
    ['resume', (q: Q) => q.resume('a'), 'POST /api/queue/a/resume', undefined],
    ['cancel', (q: Q) => q.cancel('a'), 'POST /api/queue/a/cancel', undefined],
    ['retry', (q: Q) => q.retry('a'), 'POST /api/queue/a/retry', undefined],
    ['remove', (q: Q) => q.remove('a'), 'DELETE /api/queue/a', undefined],
    ['cancel power', (q: Q) => q.cancelPower(), 'POST /api/power/cancel', undefined],
  ])('%s sends its request', async (_name, action, route, body) => {
    const queue = await loaded(job('a'))
    server.on(route, () => new Response(null, { status: 204 }))
    await action(queue)
    const [method, path] = route.split(' ')
    const sent = server.requests.filter((r) => r.method === method && r.path === path)
    expect(sent).toHaveLength(1)
    expect(sent[0]?.body).toEqual(body)
  })

  it('reads a job log from an offset', async () => {
    const queue = await loaded(job('a'))
    server.on('GET /api/queue/a/log', { text: 'line\n', next: 105, more: false })
    expect(await queue.readLog('a', 100)).toEqual({ text: 'line\n', next: 105, more: false })
    expect(server.requests.at(-1)?.search).toBe('?from=100')
  })
})

type Q = ReturnType<typeof useQueueStore>
