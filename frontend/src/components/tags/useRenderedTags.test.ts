import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, problem } from '@/api/testing/fakes'
import type { JobSettings, RenderedTags } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'

import { writtenValue } from './tags'
import { renderedFor } from './testing'
import { useRenderedTags } from './useRenderedTags'

const ROUTE = 'POST /api/jobs/tags'

function jobOf(body: unknown): JobSettings {
  return (body as { job: JobSettings }).job
}

describe('useRenderedTags', () => {
  let server: FakeServer
  let scope = effectScope()

  beforeEach(async () => {
    setActivePinia(createPinia())
    server = new FakeServer()
      .on('POST /api/jobs/draft', () => sampleDraft(sampleJob()))
      .on('POST /api/presets/diff', [])
      .on('GET /api/presets/h265-mkv-1080p', samplePreset())
      .on(ROUTE, (request) => renderedFor(jobOf(request.body)))
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    await useEditorStore().open('src')
    vi.useFakeTimers()
    scope = effectScope()
  })

  afterEach(() => {
    scope.stop()
    vi.useRealTimers()
  })

  const start = () => scope.run(() => useRenderedTags())!
  const asked = () => server.count(ROUTE)

  it('asks at once, then once 250 ms after the last edit of any setting', async () => {
    const { tags } = start()
    await vi.advanceTimersByTimeAsync(0)
    expect(asked()).toBe(1)
    const editor = useEditorStore()
    editor.set('/tags/title', '{name} A')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 50)
    editor.set('/output/container', 'mp4')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 1)
    expect(asked()).toBe(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(asked()).toBe(2)
    expect(tags.value?.values.title).toBe('multitrack A')
  })

  it('never shows an older answer over a newer one', async () => {
    const slow = deferred<RenderedTags>()
    server.on(ROUTE, (request) => {
      const job = jobOf(request.body)
      return job.tags?.title === null ? slow.promise : renderedFor(job)
    })
    const { tags } = start()
    await vi.advanceTimersByTimeAsync(0)
    useEditorStore().set('/tags/title', 'New')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(tags.value?.values.title).toBe('New')
    slow.resolve(renderedFor(sampleJob()))
    await vi.advanceTimersByTimeAsync(0)
    expect(tags.value?.values.title).toBe('New')
  })

  it('says why the server gave no values', async () => {
    server.on(ROUTE, () => problem(500, 'internal', 'Server error', 'probe failed'))
    const { failure, pending } = start()
    await vi.advanceTimersByTimeAsync(0)
    expect(failure.value).toBe('probe failed')
    expect(pending.value).toBe(false)
  })
})

describe('writtenValue', () => {
  const rendered = renderedFor({ ...sampleJob(), tags: { ...sampleJob().tags, genre: 'Drama' } })

  it('is the rendered value of a set tag', () => {
    expect(writtenValue(rendered, 'genre', true)).toEqual({ kind: 'value', text: 'Drama' })
  })

  it("is the source's value for an unset tag with passthru on", () => {
    expect(writtenValue(rendered, 'title', true)).toEqual({ kind: 'copied', text: 'Source title' })
  })

  it('is nothing for an unset tag with passthru off, or a source without the tag', () => {
    expect(writtenValue(rendered, 'title', false)).toEqual({ kind: 'none' })
    expect(writtenValue(rendered, 'plot', true)).toEqual({ kind: 'none' })
  })

  it('is unknown before the first answer', () => {
    expect(writtenValue(null, 'title', true)).toEqual({ kind: 'unknown' })
  })
})
