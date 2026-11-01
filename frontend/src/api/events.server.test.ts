import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { useQueueStore } from '@/stores/queue'
import { useSettingsStore } from '@/stores/settings'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'
import { useTasksStore } from '@/stores/tasks'
import { useToastStore } from '@/stores/toasts'

import { boot, shutdown } from './boot'
import { api, apiQuiet, ApiError, unwrap } from './client'
import { type DevServer, startServer } from './testing/devServer.mjs'
import { addJob, draftJob, endedTask, http, sleep } from './testing/serverHelpers'
import { TapSocket } from './testing/tapSocket'
import type { JobSettings } from './types'

const PORT = 8721
const TOKEN = 'events-test-token'
/** With `random` 0.5 the first reconnect waits 0.75 of `initial`. */
const BACKOFF = { initial: 1_000, max: 4_000, factor: 2 }

/** Events and reads take milliseconds; this leaves room for a loaded machine. */
const SOON = { timeout: 10_000, interval: 50 }

let server: DevServer
let job: JobSettings
let sockets: TapSocket[]
let socketsAt: number[]

async function restart(token: string): Promise<void> {
  await server.stop()
  server = await startServer({ port: PORT, args: ['--token', token] })
}

/** The dropped events of the add of `jobId`, by type. */
function addEvents(tap: TapSocket, jobId: string): string[] {
  return tap.dropped
    .filter((event) =>
      'job_ids' in event
        ? event.job_ids.includes(jobId)
        : 'job_id' in event && event.job_id === jobId,
    )
    .map((event) => event.type)
}

function lastSocket(): TapSocket {
  const socket = sockets.at(-1)
  if (socket === undefined) throw new Error('no socket yet')
  return socket
}

async function bootClient(): Promise<void> {
  await boot({
    backend: async () => ({ baseUrl: server.url }),
    token: TOKEN,
    socket: (url) => {
      const socket = new TapSocket(url)
      sockets.push(socket)
      socketsAt.push(Date.now())
      return socket
    },
    random: () => 0.5,
    connection: { backoff: BACKOFF },
  })
}

beforeAll(async () => {
  server = await startServer({ port: PORT, args: ['--token', TOKEN] })
  job = await draftJob(server)
})

afterAll(async () => {
  await server.stop()
})

beforeEach(() => {
  setActivePinia(createPinia())
  sockets = []
  socketsAt = []
})

afterEach(() => {
  shutdown()
})

describe('the stores against a real server', () => {
  it('fills every mirrored store from its snapshot at start', async () => {
    const jobId = await addJob(server, job)
    await bootClient()

    const system = useSystemStore()
    expect(system.phase).toBe('ready')
    expect(system.connection).toBe('open')
    expect(system.instance).toMatch(/\w+/)
    expect(system.info?.mode).toBe('web')
    expect(system.info?.tools.ffmpeg.status).toBe('found')
    expect(system.ffmpegProblem).toBeNull()
    expect(system.encoderStatus('libx264')?.state).toBe('available')
    expect(system.definitions?.video_encoders?.libx264).toBeDefined()
    expect(system.languages.length).toBeGreaterThan(100)
    expect(useSettingsStore().settings?.queue?.when_done).toBe('nothing')
    const queue = useQueueStore()
    expect(queue.loaded).toBe(true)
    expect(queue.byId(jobId)?.state).toBe('waiting')
    expect(queue.whenDone).toBe('nothing')
    expect(Object.values(useTasksStore().tasks).some((t) => t.kind === 'probe_sources')).toBe(true)
  })

  it('keeps the stores current by events', async () => {
    await bootClient()
    const queue = useQueueStore()
    const tasks = useTasksStore()
    const system = useSystemStore()
    const checked = system.encoderStatus('libx264')?.checked_at

    const jobId = await addJob(server, job)
    await vi.waitFor(() => expect(queue.byId(jobId)?.state).toBe('waiting'), SOON)
    await http(server, 'POST', `/api/queue/${jobId}/cancel`)
    await vi.waitFor(() => expect(queue.byId(jobId)?.state).toBe('cancelled'), SOON)
    await http(server, 'DELETE', `/api/queue/${jobId}`)
    await vi.waitFor(() => expect(queue.byId(jobId)).toBeUndefined(), SOON)

    const { task_id } = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
      paths: [`${server.media}/multitrack.mkv`],
    })
    await vi.waitFor(() => expect(tasks.tasks[task_id]?.state).toBe('done'), SOON)

    const rescan = await http<{ task_id: string }>(server, 'POST', '/api/system/encoders/rescan')
    await vi.waitFor(() => expect(system.encoderStatus('libx264')?.checked_at).not.toBe(checked), {
      timeout: 30_000,
    })
    // Its events would reach the next tests.
    await endedTask(server, rescan.task_id)
    // Only the events reached the client: the socket that is open carried them.
    expect(sockets).toHaveLength(1)
  })

  it('reconnects after a dropped connection with a backoff and reads the snapshots again', async () => {
    await bootClient()
    const system = useSystemStore()
    const queue = useQueueStore()

    const cutAt = Date.now()
    lastSocket().cut()
    expect(system.connection).toBe('reconnecting')
    // Its events go nowhere: no connection is subscribed while it is added.
    const jobId = await addJob(server, job)
    const addedAt = Date.now()
    await vi.waitFor(() => expect(system.connection).toBe('open'), { timeout: 10_000 })

    expect(sockets).toHaveLength(2)
    const waited = (socketsAt[1] ?? 0) - cutAt
    expect(waited).toBeGreaterThanOrEqual(0.75 * BACKOFF.initial - 5)
    expect(waited).toBeLessThan(BACKOFF.initial + 500)
    expect(addedAt).toBeLessThan(socketsAt[1] ?? 0)
    await vi.waitFor(() => expect(queue.byId(jobId)?.state).toBe('waiting'), SOON)
  })

  it('reads the snapshots again after a gap in the event numbers', async () => {
    await bootClient()
    const queue = useQueueStore()
    const tap = lastSocket()
    // Every event is held back, so none shows the gap before the test is ready for it.
    tap.dropWhen = () => true
    tap.dropLeavesGap = true

    const jobId = await addJob(server, job)
    await vi.waitFor(
      () => expect(addEvents(tap, jobId)).toEqual(['job.state', 'queue.changed']),
      SOON,
    )
    await sleep(300)
    expect(queue.byId(jobId)).toBeUndefined()
    tap.dropWhen = null

    // Any later event shows the gap: a probe's task events.
    await http(server, 'POST', '/api/sources', { paths: [`${server.media}/multitrack.mkv`] })
    await vi.waitFor(() => expect(queue.byId(jobId)?.state).toBe('waiting'), SOON)
  })

  it('reads the snapshots again after a resync event', async () => {
    await bootClient()
    const queue = useQueueStore()
    const tap = lastSocket()
    tap.dropWhen = (event) => event.type === 'job.state' || event.type === 'queue.changed'
    tap.dropLeavesGap = false

    const jobId = await addJob(server, job)
    await vi.waitFor(
      () => expect(addEvents(tap, jobId)).toEqual(['job.state', 'queue.changed']),
      SOON,
    )
    tap.dropWhen = null
    // Later events pass, numbered without a gap: they read nothing.
    await http(server, 'POST', '/api/sources', { paths: [`${server.media}/multitrack.mkv`] })
    await sleep(300)
    expect(queue.byId(jobId)).toBeUndefined()

    tap.inject({ type: 'resync', reason: 'dropped', dropped: 2 })
    await vi.waitFor(() => expect(queue.byId(jobId)?.state).toBe('waiting'), SOON)
  })

  it('turns a problem+json answer into a toast, and through apiQuiet it does not', async () => {
    await bootClient()
    const toasts = useToastStore()
    const path = { params: { path: { job_id: 'no-such-job' } } }

    const loud = await api.GET('/api/queue/{job_id}/log', path)
    expect(() => unwrap(loud)).toThrow(ApiError)
    expect(toasts.items).toHaveLength(1)
    expect(toasts.items[0]).toMatchObject({ severity: 'error', summary: 'No job no-such-job' })

    const quiet = await apiQuiet.GET('/api/queue/{job_id}/log', path)
    let error: unknown
    try {
      unwrap(quiet)
    } catch (caught) {
      error = caught
    }
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(404)
    expect((error as ApiError).problem.code).toBe('queue.unknown_job')
    expect(toasts.items).toHaveLength(1)
  })

  it('re-probes the sources after a hello from another server run', async () => {
    await bootClient()
    const system = useSystemStore()
    const queue = useQueueStore()
    const restarted = vi.spyOn(useSourcesStore(), 'onServerRestart').mockResolvedValue()
    const before = system.instance
    await addJob(server, job)
    await vi.waitFor(() => expect(queue.jobs.length).toBeGreaterThan(0), SOON)

    await restart(TOKEN)
    await vi.waitFor(() => expect(system.instance).not.toBe(before), { timeout: 20_000 })

    expect(system.connection).toBe('open')
    expect(restarted).toHaveBeenCalledTimes(1)
    // The new run has a new home: its queue is empty, and the copy follows it.
    await vi.waitFor(() => expect(queue.jobs).toEqual([]), SOON)
    job = await draftJob(server)
  })

  it('does not retry a 4401 close with the same credentials', async () => {
    await bootClient()
    const system = useSystemStore()
    vi.spyOn(useSourcesStore(), 'onServerRestart').mockResolvedValue()

    await restart('another-token')
    await vi.waitFor(() => expect(system.connection).toBe('unauthorized'), { timeout: 20_000 })
    expect(system.phase).toBe('login')
    const attempts = sockets.length
    await sleep(2.5 * BACKOFF.max)
    expect(sockets).toHaveLength(attempts)
    expect(lastSocket().sent).toEqual([JSON.stringify({ type: 'auth', token: TOKEN })])

    expect(await system.loginWithToken('another-token')).toBe(true)
    await vi.waitFor(() => expect(system.phase).toBe('ready'), SOON)
    expect(system.connection).toBe('open')
    expect(lastSocket().sent).toEqual([JSON.stringify({ type: 'auth', token: 'another-token' })])
  })
})
