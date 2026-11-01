import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'

import { boot, shutdown } from '@/api/boot'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http, sleep } from '@/api/testing/serverHelpers'
import type { JobSettings, QueueJob } from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'
import { useActivityStore } from '@/stores/activity'
import { useQueueStore } from '@/stores/queue'

import { useJobLog } from './useJobLog'

const PORT = 8731
const TOKEN = 'queue-k-test-token'
const SOON = { timeout: 30_000, interval: 50 }

let server: DevServer

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: [
      '--token',
      TOKEN,
      '--fixtures',
      'hdr10-4k,multitrack',
      ...(tools === null ? [] : ['--tools-dir', tools]),
    ],
  })
}, 120_000)

afterAll(async () => {
  await server.stop()
})

beforeEach(async () => {
  setActivePinia(createPinia())
  await boot({ backend: async () => ({ baseUrl: server.url }), token: TOKEN })
})

afterEach(() => {
  shutdown()
})

async function draft(file: string): Promise<JobSettings> {
  const { task_id } = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
    paths: [`${server.media}/${file}`],
  })
  const task = await endedTask(server, task_id)
  const { sources } = task.result as { sources: { id: string }[] }
  const answer = await http<{ job: JobSettings }>(server, 'POST', '/api/jobs/draft', {
    source_id: sources[0]?.id,
  })
  return answer.job
}

function named(job: JobSettings, name: string): JobSettings {
  const path = String(job.output?.path).replace(/[^/]*$/, `${name}.mkv`)
  return { ...job, output: { ...job.output, path } } as JobSettings
}

/** A 4K x265 encode at its slowest preset: it runs long enough to stop the queue under it. */
function slow(job: JobSettings, name: string): JobSettings {
  const size = { ...job.dimensions?.size, width: 3840, height: 2160 }
  return named(
    {
      ...job,
      dimensions: { ...job.dimensions, size },
      video: { ...job.video, preset: 'placebo' },
    } as JobSettings,
    name,
  )
}

describe('the queue against a real server', () => {
  it('follows a Stop and a Start, and another front end’s start of its own jobs to its idle end', async () => {
    const queue = useQueueStore()
    const activity = useActivityStore()
    const [long, quick] = await queue.add([
      slow(await draft('hdr10-4k.mkv'), 'long'),
      named(await draft('multitrack.mkv'), 'quick'),
    ])
    if (long === undefined || quick === undefined) throw new Error('two jobs expected')
    const stateOf = (job: QueueJob) => queue.byId(job.id)?.state
    expect([queue.processing, queue.only]).toEqual([false, null])

    // Another front end (a CLI) starts only its own job.
    await http(server, 'POST', '/api/queue/start', { job_ids: [long.id] })
    await vi.waitFor(() => expect([queue.processing, queue.only]).toEqual([true, [long.id]]), SOON)
    await vi.waitFor(() => expect(stateOf(long)).toBe('running'), SOON)
    expect(stateOf(quick)).toBe('waiting')

    // Start without ids widens the run to every waiting job; the one slot is busy, so it waits.
    await queue.start()
    await vi.waitFor(() => expect([queue.processing, queue.only]).toEqual([true, null]), SOON)

    // Stop: the running job goes on and the waiting one is not taken, not even when the slot frees.
    await queue.stop()
    await vi.waitFor(() => expect(queue.processing).toBe(false), SOON)
    await sleep(1500)
    expect([stateOf(long), stateOf(quick)]).toEqual(['running', 'waiting'])
    await queue.cancel(long.id)
    await vi.waitFor(() => expect(stateOf(long)).toBe('cancelled'), SOON)
    await sleep(1500)
    expect(stateOf(quick)).toBe('waiting')
    expect((await http<{ processing: boolean }>(server, 'GET', '/api/queue')).processing).toBe(
      false,
    )

    // Start again: the waiting job runs.
    await queue.start()
    await vi.waitFor(() => expect(stateOf(quick)).toBe('done'), { timeout: 120_000, interval: 100 })
    expect([queue.processing, queue.only]).toEqual([true, null])

    // A start whose named jobs have all ended goes idle at once.
    await queue.stop()
    await vi.waitFor(() => expect(queue.processing).toBe(false), SOON)
    await http(server, 'POST', '/api/queue/start', { job_ids: [quick.id] })
    await vi.waitFor(() => {
      const reasons = activity.entries.flatMap((entry) =>
        entry.event.type === 'queue.processing' ? [entry.event.reason] : [],
      )
      expect(reasons).toEqual(['start', 'start', 'stop', 'start', 'stop', 'start', 'idle'])
    }, SOON)
    expect([queue.processing, queue.only]).toEqual([false, null])
  }, 240_000)

  it('follows a job’s log from before its start to its end, and ends with the whole log', async () => {
    const queue = useQueueStore()
    const [job] = await queue.add([named(await draft('multitrack.mkv'), 'logged')])
    if (job === undefined) throw new Error('one job expected')
    const scope = effectScope()
    const log = scope.run(() => useJobLog(ref(job.id)))
    if (log === undefined) throw new Error('no log')
    try {
      await vi.waitFor(() => expect(log.loading.value).toBe(false), SOON)
      // Before the first run the server's log is empty.
      expect(log.lines.value).toEqual([])
      await queue.start([job.id])
      await vi.waitFor(() => expect(queue.byId(job.id)?.state).toBe('done'), {
        timeout: 120_000,
        interval: 100,
      })
      expect(queue.logTicks[job.id] ?? 0).toBeGreaterThan(0)
      const whole = await http<{ text: string; more: boolean }>(
        server,
        'GET',
        `/api/queue/${job.id}/log`,
      )
      expect(whole.more).toBe(false)
      await vi.waitFor(() => expect(log.text()).toBe(whole.text), SOON)
      expect(log.lines.value[0]).toMatch(/^=== Reframe job .*: run started /)
    } finally {
      scope.stop()
    }
  }, 180_000)
})
