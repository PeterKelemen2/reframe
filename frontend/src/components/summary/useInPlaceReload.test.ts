import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope, nextTick, reactive } from 'vue'

import { ApiError } from '@/api/client'
import type { JobSettings, JobState, QueueJob, SourceEntry } from '@/api/types'

import { useInPlaceReload } from './useInPlaceReload'

const queue = reactive({ loaded: false, jobs: [] as QueueJob[] })
const sources = reactive({
  entries: [] as SourceEntry[],
  reload: vi.fn<(id: string) => Promise<void>>(async () => {}),
})
vi.mock('@/stores/queue', () => ({ useQueueStore: () => queue }))
vi.mock('@/stores/sources', () => ({ useSourcesStore: () => sources }))

function entry(id: string): SourceEntry {
  return { id, path: `/output/${id}.mkv`, source: null }
}

/** A job of `/output/<source>.mkv`; `inPlace`: it edits that file instead of writing a new one. */
function job(
  id: string,
  state: JobState,
  { source = 'show', inPlace = true, started = state !== 'waiting' } = {},
): QueueJob {
  return {
    id,
    position: 0,
    state,
    settings: {
      source: { path: `/output/${source}.mkv` },
      output: { path: `/output/${source}.mkv`, edit_in_place: inPlace },
    } as unknown as JobSettings,
    issues: [],
    created_at: '2026-11-01T10:00:00Z',
    started_at: started ? '2026-11-01T10:00:01Z' : null,
  } as QueueJob
}

let scope: EffectScope

beforeEach(() => {
  queue.loaded = false
  queue.jobs = []
  sources.entries = [entry('show'), entry('movie')]
  sources.reload.mockClear()
  scope = effectScope()
  scope.run(() => useInPlaceReload())
})

afterEach(() => {
  scope.stop()
})

/** The queue's jobs as the next event or read leaves them. */
async function become(...jobs: QueueJob[]): Promise<void> {
  queue.jobs = jobs
  await nextTick()
}

async function firstRead(...jobs: QueueJob[]): Promise<void> {
  queue.loaded = true
  await become(...jobs)
}

describe('reading a source again after an in-place edit', () => {
  it('reads the open source when its in-place job ends, once', async () => {
    await firstRead(job('a', 'waiting'))
    await become(job('a', 'running'))
    expect(sources.reload).not.toHaveBeenCalled()
    await become(job('a', 'done'))
    expect(sources.reload).toHaveBeenCalledExactlyOnceWith('show')
    // The read after the end brings the server's times: the job is still the same end.
    await become({ ...job('a', 'done'), finished_at: '2026-11-01T10:00:02Z' })
    expect(sources.reload).toHaveBeenCalledOnce()
  })

  it('reads it again after a retry of the job ends', async () => {
    await firstRead(job('a', 'done'))
    await become(job('a', 'waiting'))
    await become(job('a', 'done'))
    expect(sources.reload).toHaveBeenCalledExactlyOnceWith('show')
  })

  it('reads it for a stopped edit too: the header may have been written', async () => {
    await firstRead(job('a', 'running'), job('b', 'running', { source: 'movie' }))
    await become(job('a', 'cancelled'), job('b', 'failed', { source: 'movie' }))
    expect(sources.reload.mock.calls).toEqual([['show'], ['movie']])
  })

  it('reads it for an edit that this window first sees ended (another window ran it)', async () => {
    await firstRead()
    await become(job('a', 'done'))
    expect(sources.reload).toHaveBeenCalledExactlyOnceWith('show')
  })

  it('reads nothing for the jobs that had ended before the first read of the queue', async () => {
    await become(job('a', 'done'))
    await firstRead(job('a', 'done'))
    expect(sources.reload).not.toHaveBeenCalled()
  })

  it('reads nothing for a job that writes a new file', async () => {
    await firstRead(job('a', 'running', { inPlace: false }))
    await become(job('a', 'done', { inPlace: false }))
    expect(sources.reload).not.toHaveBeenCalled()
  })

  it('reads nothing for an in-place job that never ran (refused when it was added)', async () => {
    await firstRead()
    await become(job('a', 'failed', { started: false }))
    expect(sources.reload).not.toHaveBeenCalled()
  })

  it('reads only the source the job edited, and nothing when it is not open', async () => {
    await firstRead(job('a', 'running'), job('b', 'running', { source: 'elsewhere' }))
    await become(job('a', 'done'), job('b', 'done', { source: 'elsewhere' }))
    expect(sources.reload.mock.calls).toEqual([['show']])
  })

  it('lets a refused read go: the sources store has shown it', async () => {
    sources.reload.mockRejectedValueOnce(
      new ApiError(500, {
        type: 'about:blank',
        code: 'server.error',
        title: 'Internal error',
        status: 500,
      }),
    )
    await firstRead(job('a', 'running'))
    await become(job('a', 'done'))
    await vi.waitFor(() => expect(sources.reload).toHaveBeenCalledOnce())
  })
})
