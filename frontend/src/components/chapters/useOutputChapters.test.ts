import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, problem } from '@/api/testing/fakes'
import type { JobSettings, OutputChapters } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'

import { chaptersOf } from './testing'
import { useOutputChapters } from './useOutputChapters'

const ROUTE = 'POST /api/jobs/chapters'

let server: FakeServer
let scope = effectScope()

function jobOf(body: unknown): JobSettings {
  return (body as { job: JobSettings }).job
}

beforeEach(async () => {
  setActivePinia(createPinia())
  server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(sampleJob()))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
    .on(ROUTE, (request) => chaptersOf(jobOf(request.body)))
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  await useEditorStore().open('src')
  vi.useFakeTimers()
  scope = effectScope()
})

afterEach(() => {
  scope.stop()
  vi.useRealTimers()
})

const start = () => scope.run(() => useOutputChapters())!
const asked = () => server.count(ROUTE)

it('asks at once for the open job', async () => {
  const { chapters, pending } = start()
  expect(pending.value).toBe(true)
  await vi.advanceTimersByTimeAsync(0)
  expect(asked()).toBe(1)
  expect(chapters.value?.chapters.map((c) => c.name)).toEqual(['Opening', 'Part One', 'Part Two'])
  expect(pending.value).toBe(false)
})

it('asks once, 250 ms after the last edit of the chapters, for the newest job', async () => {
  const { chapters } = start()
  await vi.advanceTimersByTimeAsync(0)
  const editor = useEditorStore()
  editor.set('/chapters/names', ['A'])
  await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 50)
  editor.set('/chapters/names', ['B'])
  await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 1)
  expect(asked()).toBe(1)
  await vi.advanceTimersByTimeAsync(1)
  expect(asked()).toBe(2)
  expect(jobOf(server.requests.at(-1)!.body).chapters?.names).toEqual(['B'])
  expect(chapters.value?.chapters[0]?.name).toBe('B')
})

it('asks again after a change of the range', async () => {
  start()
  await vi.advanceTimersByTimeAsync(0)
  useEditorStore().set('/range', { kind: 'chapters', start: 2, end: 3 })
  await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
  expect(asked()).toBe(2)
})

it('asks nothing for an edit the chapters do not depend on', async () => {
  start()
  await vi.advanceTimersByTimeAsync(0)
  useEditorStore().set('/tags/title', 'A title')
  await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE * 2)
  expect(asked()).toBe(1)
})

it('never shows an older answer over a newer one', async () => {
  const slow = deferred<OutputChapters>()
  server.on(ROUTE, (request) => {
    const job = jobOf(request.body)
    return job.chapters?.names === null ? slow.promise : chaptersOf(job)
  })
  const { chapters } = start()
  await vi.advanceTimersByTimeAsync(0)
  useEditorStore().set('/chapters/names', ['New'])
  await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
  expect(chapters.value?.chapters[0]?.name).toBe('New')
  slow.resolve(chaptersOf(sampleJob()))
  await vi.advanceTimersByTimeAsync(0)
  expect(chapters.value?.chapters[0]?.name).toBe('New')
})

it("says why the server gave no list, and keeps the last list's place empty for a new job", async () => {
  server.on(ROUTE, () => problem(422, 'jobs.invalid', 'Invalid', 'The source is gone'))
  const { chapters, failure } = start()
  await vi.advanceTimersByTimeAsync(0)
  expect(failure.value).toBe('The source is gone')
  expect(chapters.value).toBeNull()
})

it('forgets the last job’s chapters when another job opens', async () => {
  const { chapters } = start()
  await vi.advanceTimersByTimeAsync(0)
  const answer = deferred<OutputChapters>()
  server.on(ROUTE, () => answer.promise)
  vi.useRealTimers()
  await useEditorStore().open('other')
  expect(chapters.value).toBeNull()
})
