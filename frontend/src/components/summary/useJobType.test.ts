import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'

import { configureClient } from '@/api/client'
import { type Deferred, deferred, FakeServer, problem } from '@/api/testing/fakes'
import type { JobSettings, JobTypeInfo } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'

import { useJobType } from './useJobType'

function typeOf(job_type: JobTypeInfo['job_type'], reason = `${job_type}: why`): JobTypeInfo {
  return { job_type, reason, in_place_blockers: [] }
}

describe('the job type of the open job', () => {
  let server: FakeServer
  let scope: EffectScope
  let answers: Deferred<unknown>[]

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    answers = []
    server = new FakeServer()
      .on('POST /api/jobs/draft', (request) => {
        const job = sampleJob()
        job.source.path = `/media/${(request.body as { source_id: string }).source_id}.mkv`
        return sampleDraft(job)
      })
      .on('POST /api/presets/diff', [])
      .on('GET /api/presets/h265-mkv-1080p', samplePreset())
      .on('POST /api/jobs/type', () => {
        const pending = deferred<unknown>()
        answers.push(pending)
        return pending.promise
      })
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    scope = effectScope()
  })

  afterEach(() => {
    scope.stop()
    vi.useRealTimers()
  })

  function sent(): JobSettings[] {
    return server.requests
      .filter((request) => request.path === '/api/jobs/type')
      .map((request) => (request.body as { job: JobSettings }).job)
  }

  async function opened(sourceId = 'movie') {
    const editor = useEditorStore()
    await editor.open(sourceId)
    const jobType = scope.run(() => useJobType())!
    await vi.advanceTimersByTimeAsync(0)
    return { editor, jobType }
  }

  async function answer(index: number, value: unknown): Promise<void> {
    answers[index]!.resolve(value)
    await vi.advanceTimersByTimeAsync(0)
  }

  it('asks at once for a new job and shows the answer', async () => {
    const { jobType } = await opened()
    expect(sent()).toHaveLength(1)
    expect(sent()[0]!.source.path).toBe('/media/movie.mkv')
    expect(jobType.pending.value).toBe(true)
    await answer(0, typeOf('encode'))
    expect(jobType.answer.value).toEqual(typeOf('encode'))
    expect(jobType.pending.value).toBe(false)
  })

  it('asks once, 250 ms after the last of several edits, with the job as it is then', async () => {
    const { editor, jobType } = await opened()
    await answer(0, typeOf('encode'))
    editor.set('/video/passthrough', true)
    await vi.advanceTimersByTimeAsync(100)
    editor.set('/audio/0/action', 'passthru')
    await vi.advanceTimersByTimeAsync(100)
    editor.set('/output/edit_in_place', true)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 1)
    expect(sent()).toHaveLength(1)
    // The last answer stays on screen, marked as being updated.
    expect(jobType.answer.value?.job_type).toBe('encode')
    expect(jobType.pending.value).toBe(true)
    await vi.advanceTimersByTimeAsync(1)
    expect(sent()).toHaveLength(2)
    expect(sent()[1]!.output?.edit_in_place).toBe(true)
    expect(sent()[1]!.audio?.[0]?.action).toBe('passthru')
    await answer(1, typeOf('metadata_edit'))
    expect(jobType.answer.value?.job_type).toBe('metadata_edit')
  })

  it('never shows an older answer over a newer one', async () => {
    const { editor, jobType } = await opened()
    editor.set('/video/passthrough', true)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(sent()).toHaveLength(2)
    await answer(1, typeOf('remux'))
    await answer(0, typeOf('encode'))
    expect(jobType.answer.value?.job_type).toBe('remux')
    expect(jobType.pending.value).toBe(false)
  })

  it("drops the last job's type at once when another job opens, and asks at once", async () => {
    const { editor, jobType } = await opened('movie')
    await answer(0, typeOf('remux'))
    await editor.open('other')
    expect(jobType.answer.value).toBeNull()
    await vi.advanceTimersByTimeAsync(0)
    expect(sent()).toHaveLength(2)
    expect(sent()[1]!.source.path).toBe('/media/other.mkv')
  })

  it('forgets the type and the request when the job closes', async () => {
    const { editor, jobType } = await opened()
    editor.close()
    await answer(0, typeOf('encode'))
    expect(jobType.answer.value).toBeNull()
    expect(jobType.pending.value).toBe(false)
  })

  it("shows the server's reason when it cannot tell the type", async () => {
    server.on('POST /api/jobs/type', () =>
      problem(403, 'path.outside_roots', 'The path is outside the allowed folders'),
    )
    const { jobType } = await opened()
    expect(jobType.error.value).toBe('The path is outside the allowed folders')
    expect(jobType.answer.value).toBeNull()
    expect(jobType.pending.value).toBe(false)
  })
})
