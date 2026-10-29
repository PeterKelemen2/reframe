import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'

import { configureClient } from '@/api/client'
import { type Deferred, deferred, FakeServer, problem } from '@/api/testing/fakes'
import type { Schemas } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'

import { useGeometry } from './useGeometry'

type JobGeometry = Schemas['JobGeometry']

function geometryOf(width: number): JobGeometry {
  return {
    source: {
      width: 320,
      height: 180,
      rotation: 0,
      chroma_step_x: 2,
      chroma_step_y: 2,
      interlaced: false,
      chroma_assumed: false,
    },
    geometry: {
      crop: { top: 0, bottom: 0, left: 0, right: 0 },
      cropped_width: 320,
      cropped_height: 180,
      scaled_width: width,
      scaled_height: 180,
      output_sar: { num: 1, den: 1 },
      display_aspect: 16 / 9,
      rotation: 0,
      upscaled: false,
      filter_rotation: 0,
      flip_horizontal: false,
    },
  }
}

describe('the geometry of the open job', () => {
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
      .on('POST /api/jobs/geometry', () => {
        const answer = deferred<unknown>()
        answers.push(answer)
        return answer.promise
      })
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    scope = effectScope()
  })

  afterEach(() => {
    scope.stop()
    vi.useRealTimers()
  })

  function requests() {
    return server.requests.filter((request) => request.path === '/api/jobs/geometry')
  }

  async function opened(sourceId = 'movie') {
    const editor = useEditorStore()
    await editor.open(sourceId)
    const geometry = scope.run(() => useGeometry())!
    await vi.advanceTimersByTimeAsync(0)
    return { editor, geometry }
  }

  it('asks at once for a new job and shows the answer', async () => {
    const { geometry } = await opened()
    expect(requests()).toHaveLength(1)
    expect((requests()[0]!.body as { job: { source: { path: string } } }).job.source.path).toBe(
      '/media/movie.mkv',
    )
    answers[0]!.resolve(geometryOf(320))
    await vi.advanceTimersByTimeAsync(0)
    expect(geometry.answer.value?.geometry?.scaled_width).toBe(320)
    expect(geometry.pending.value).toBe(false)
  })

  it('asks once, 250 ms after the last of several dimension edits', async () => {
    const { editor } = await opened()
    answers[0]!.resolve(geometryOf(320))
    await vi.advanceTimersByTimeAsync(0)
    editor.set('/dimensions/size', { mode: 'width', width: 1280 })
    await vi.advanceTimersByTimeAsync(100)
    editor.set('/dimensions/size', { mode: 'width', width: 1024 })
    await vi.advanceTimersByTimeAsync(100)
    editor.set('/dimensions/size', { mode: 'width', width: 640 })
    await vi.advanceTimersByTimeAsync(100)
    expect(requests()).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(requests()).toHaveLength(2)
    const sent = requests()[1]!.body as { job: { dimensions: { size: { width: number } } } }
    expect(sent.job.dimensions.size.width).toBe(640)
  })

  it('sends nothing for an edit that does not change the picture', async () => {
    const { editor } = await opened()
    editor.set('/audio/0/bitrate', 192)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE * 2)
    expect(requests()).toHaveLength(1)
  })

  it('never shows an older answer over a newer one', async () => {
    const { editor, geometry } = await opened()
    editor.set('/video/passthrough', true)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(requests()).toHaveLength(2)
    answers[1]!.resolve(geometryOf(640))
    await vi.advanceTimersByTimeAsync(0)
    answers[0]!.resolve(geometryOf(320))
    await vi.advanceTimersByTimeAsync(0)
    expect(geometry.answer.value?.geometry?.scaled_width).toBe(640)
  })

  it("drops the last job's picture at once when another job opens", async () => {
    const { editor, geometry } = await opened('movie')
    answers[0]!.resolve(geometryOf(320))
    await vi.advanceTimersByTimeAsync(0)
    await editor.open('other')
    expect(geometry.answer.value).toBeNull()
    await vi.advanceTimersByTimeAsync(0)
    expect(requests()).toHaveLength(2)
  })

  it("shows the server's reason when it cannot compute the geometry", async () => {
    server.on('POST /api/jobs/geometry', () =>
      problem(422, 'request.invalid', 'The request is not valid'),
    )
    const { geometry } = await opened()
    expect(geometry.error.value).toBe('The request is not valid')
    expect(geometry.answer.value).toBeNull()
  })
})
