import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope, nextTick, ref } from 'vue'

import { ApiError } from '@/api/client'
import { deferred } from '@/api/testing/fakes'
import type { JobLogChunk } from '@/api/types'

import { job, queueDouble, resetQueue } from './testing'
import { useJobLog } from './useJobLog'

const queue = queueDouble()
vi.mock('@/stores/queue', () => ({ useQueueStore: () => queue }))

/** A log file the fake `readLog` serves in chunks of `size` bytes (ASCII, so bytes = chars). */
let file = ''
let size = 1 << 20
const scopes: EffectScope[] = []

afterEach(() => {
  for (const scope of scopes.splice(0)) scope.stop()
})

beforeEach(() => {
  resetQueue(queue)
  vi.clearAllMocks()
  file = ''
  size = 1 << 20
  queue.readLog.mockImplementation(async (_id: string, from = 0): Promise<JobLogChunk> => {
    const text = file.slice(from, from + size)
    return { text, next: from + text.length, more: from + text.length < file.length }
  })
})

function open(id: string | null = 'a') {
  const jobId = ref<string | null>(id)
  const scope = effectScope()
  scopes.push(scope)
  const log = scope.run(() => useJobLog(jobId))
  if (log === undefined) throw new Error('no log')
  return { jobId, log, scope }
}

const froms = () => queue.readLog.mock.calls.map(([, from]) => from)

describe('a job log', () => {
  it('reads the whole log in chunks, with a line that a chunk end cut in two whole again', async () => {
    file = 'first line\nsecond line\nthird'
    size = 7
    const { log } = open()
    await flushPromises()
    expect(log.lines.value).toEqual(['first line', 'second line', 'third'])
    expect(froms()).toEqual([0, 7, 14, 21])
    expect(log.text()).toBe(file)
    expect(log.loading.value).toBe(false)
  })

  it('reads on from where it stopped when the job writes more', async () => {
    queue.jobs = [job('a', 'running')]
    file = 'one\n'
    const { log } = open()
    await flushPromises()
    file += 'two\n'
    queue.logTicks = { a: 1 }
    await flushPromises()
    expect(log.lines.value).toEqual(['one', 'two'])
    expect(froms()).toEqual([0, 4])
  })

  it('makes one more read after the one under way for any number of writes during it', async () => {
    queue.jobs = [job('a', 'running')]
    file = 'one\n'
    const { log } = open()
    await flushPromises()
    const held = deferred<JobLogChunk>()
    queue.readLog.mockImplementationOnce(() => held.promise)
    queue.logTicks = { a: 1 }
    await nextTick()
    queue.logTicks = { a: 2 }
    await nextTick()
    queue.logTicks = { a: 3 }
    await nextTick()
    file += 'two\nthree\n'
    held.resolve({ text: 'two\n', next: 8, more: false })
    await flushPromises()
    expect(log.lines.value).toEqual(['one', 'two', 'three'])
    expect(froms()).toEqual([0, 4, 8])
  })

  it('reads once more when the job ends', async () => {
    queue.jobs = [job('a', 'running')]
    file = 'one\n'
    const { log } = open()
    await flushPromises()
    file += 'encoded 120 frames\n'
    queue.jobs = [job('a', 'done')]
    await flushPromises()
    expect(log.lines.value).toEqual(['one', 'encoded 120 frames'])
  })

  it('starts again for another job and drops a late answer of the one before', async () => {
    const held = deferred<JobLogChunk>()
    queue.readLog.mockImplementationOnce(() => held.promise)
    const { jobId, log } = open('a')
    await nextTick()
    file = 'b log\n'
    jobId.value = 'b'
    await flushPromises()
    held.resolve({ text: 'a log\n', next: 6, more: false })
    await flushPromises()
    expect(log.lines.value).toEqual(['b log'])
    expect(queue.readLog.mock.calls.at(-1)).toEqual(['b', 0])
  })

  it('says that the log could not be read when the server refuses it', async () => {
    queue.readLog.mockRejectedValueOnce(
      new ApiError(404, { title: 'No job', status: 404 } as never),
    )
    const { log } = open()
    await flushPromises()
    expect(log.failed.value).toBe(true)
    expect(log.loading.value).toBe(false)
  })
})
