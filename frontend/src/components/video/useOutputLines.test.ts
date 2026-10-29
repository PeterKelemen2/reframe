import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'

import { deferred, problem } from '@/api/testing/fakes'
import type { JobSettings, Schemas, SourceEntry } from '@/api/types'
import { EDIT_DEBOUNCE } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'

import { openJob, setUpVideo } from './testing'
import { useOutputLines } from './useOutputLines'

type JobGeometry = Schemas['JobGeometry']

const SOURCE = {
  width: 1920,
  height: 1080,
  rotation: 0,
  chroma_step_x: 2,
  chroma_step_y: 2,
  interlaced: false,
  chroma_assumed: false,
} as const

function geometry(width: number, height: number): JobGeometry {
  return {
    source: SOURCE,
    geometry: {
      crop: { top: 0, bottom: 0, left: 0, right: 0 },
      cropped_width: width,
      cropped_height: height,
      scaled_width: width,
      scaled_height: height,
      output_sar: { num: 1, den: 1 },
      display_aspect: width / height,
      rotation: 0,
      upscaled: false,
      filter_rotation: 0,
      flip_horizontal: false,
    },
  }
}

/** The answer follows the job's fit box, so each edit gives another size. */
function sizeOf(job: JobSettings): JobGeometry {
  const size = job.dimensions?.size as { width?: number; height?: number }
  return geometry(size.width ?? 1920, size.height ?? 1080)
}

describe('useOutputLines', () => {
  let setup: ReturnType<typeof setUpVideo>
  let scope = effectScope()

  beforeEach(async () => {
    scope = effectScope()
    setup = setUpVideo()
    setup.server.on('POST /api/jobs/geometry', (request) =>
      sizeOf((request.body as { job: JobSettings }).job),
    )
    await openJob()
    vi.useFakeTimers()
  })

  afterEach(() => {
    scope.stop()
    vi.useRealTimers()
  })

  const asked = () => setup.server.count('POST /api/jobs/geometry')
  const start = () => scope.run(() => useOutputLines())!.lines

  it("asks at once for the open job, and gives the output picture's short side", async () => {
    const lines = start()
    await vi.advanceTimersByTimeAsync(0)
    expect(asked()).toBe(1)
    expect(lines.value).toBe(1080)
  })

  it('asks again only for an edit that can change the size, after the debounce', async () => {
    const lines = start()
    await vi.advanceTimersByTimeAsync(0)
    setup.editor.set('/video/rate_control/value', 30)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(asked()).toBe(1)
    setup.editor.set('/dimensions/size/height', 720)
    setup.editor.set('/dimensions/size/width', 1280)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 1)
    expect(asked()).toBe(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(asked()).toBe(2)
    expect(lines.value).toBe(720)
  })

  it('takes the short side of a portrait picture', async () => {
    setup.server.on('POST /api/jobs/geometry', geometry(1080, 1920))
    const lines = start()
    await vi.advanceTimersByTimeAsync(0)
    expect(lines.value).toBe(1080)
  })

  it('never shows an older answer over a newer one', async () => {
    const slow = deferred<JobGeometry>()
    setup.server.on('POST /api/jobs/geometry', (request) => {
      const job = (request.body as { job: JobSettings }).job
      return (job.dimensions!.size as { height: number }).height === 1080
        ? slow.promise
        : sizeOf(job)
    })
    const lines = start()
    await vi.advanceTimersByTimeAsync(0)
    setup.editor.set('/dimensions/size/height', 480)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(lines.value).toBe(480)
    slow.resolve(geometry(1920, 1080))
    await vi.advanceTimersByTimeAsync(0)
    expect(lines.value).toBe(480)
  })

  it("falls back to the source's size for a copied video", async () => {
    setup.server.on('POST /api/jobs/geometry', {
      source: { ...SOURCE, height: 800 },
      geometry: null,
    })
    const lines = start()
    await vi.advanceTimersByTimeAsync(0)
    expect(lines.value).toBe(800)
  })

  it('falls back to the open source when the size cannot be computed', async () => {
    setup.server.on('POST /api/jobs/geometry', () => problem(404, 'sources.unknown', 'No source'))
    const sources = useSourcesStore()
    sources.entries = [
      {
        id: 's',
        path: '/m/a.mkv',
        source: { video: [{ width: 640, height: 360 }] },
      } as unknown as SourceEntry,
    ]
    sources.activeId = 's'
    const lines = start()
    await vi.advanceTimersByTimeAsync(0)
    expect(lines.value).toBe(360)
  })
})
