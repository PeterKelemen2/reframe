import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { type Deferred, deferred, FakeServer, problem } from '@/api/testing/fakes'
import type { AppSettings, FrameLink, Frames, MediaSource } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'

import { EDIT_DEBOUNCE, useEditorStore } from './editor'
import { usePreviewStore } from './preview'
import { useSettingsStore } from './settings'
import { useSourcesStore } from './sources'

interface FramesBody {
  source_id: string
  count?: number
  timestamps?: number[]
}

interface RenderBody {
  job: { source: { path: string }; dimensions: { size: { width: number } } }
  timestamp: number
}

function frame(source: string, timestamp: number, kind: FrameLink['kind'] = 'source'): FrameLink {
  const key = `${source}-${Math.round(timestamp * 1000)}-${kind}`
  return {
    key,
    kind,
    timestamp,
    width: 320,
    height: 180,
    cached: false,
    url: `/api/preview/frames/${key}.png?exp=1&sig=s`,
  }
}

function strip(source: string, count = 10): Frames {
  return {
    frames: Array.from({ length: count }, (_, at) => frame(source, 0.2 + at * 0.4)),
    notes: [],
  }
}

async function shown(sourceId = 'movie') {
  const editor = useEditorStore()
  const preview = usePreviewStore()
  await editor.open(sourceId)
  await vi.advanceTimersByTimeAsync(0)
  return { editor, preview }
}

function renderAnswer(job: RenderBody, notes: string[] = []): Frames {
  const width = job.job.dimensions.size.width
  return {
    frames: [
      frame('movie', job.timestamp),
      { ...frame(`out${width}`, job.timestamp, 'output'), width },
    ],
    notes,
  }
}

async function rendering() {
  const opened = await shown()
  opened.preview.panelOpen = true
  opened.preview.viewMode = 'split'
  await vi.advanceTimersByTimeAsync(0)
  return opened
}

describe('the preview store', () => {
  let server: FakeServer
  let signals: { path: string; body: unknown; signal: AbortSignal }[]
  let frames: Deferred<unknown>[]
  let renders: Deferred<unknown>[]
  let holdFrames: boolean

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    signals = []
    frames = []
    renders = []
    holdFrames = false
    server = new FakeServer()
      .on('POST /api/jobs/draft', (request) => {
        const job = sampleJob()
        job.source.path = `/media/${(request.body as { source_id: string }).source_id}.mkv`
        return sampleDraft(job)
      })
      .on('POST /api/presets/diff', [])
      .on('GET /api/presets/h265-mkv-1080p', samplePreset())
      .on('POST /api/preview/frames', (request) => {
        const body = request.body as FramesBody
        if (holdFrames) {
          const answer = deferred<unknown>()
          frames.push(answer)
          return answer.promise
        }
        if (body.timestamps === undefined) return strip(body.source_id, body.count ?? 10)
        return { frames: body.timestamps.map((t) => frame(body.source_id, t)), notes: [] }
      })
      .on('POST /api/preview/render', () => {
        const answer = deferred<unknown>()
        renders.push(answer)
        return answer.promise
      })
    const fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const request = new Request(input, init)
      const copy = request.clone()
      const text = await copy.text()
      signals.push({
        path: new URL(request.url).pathname,
        body: text ? JSON.parse(text) : undefined,
        signal: request.signal,
      })
      return server.fetch(request)
    }
    configureClient({ baseUrl: 'http://server', token: 't', fetch })
  })

  afterEach(() => {
    // A store of the last test would send to the next test's server.
    usePreviewStore().$dispose()
    useEditorStore().$dispose()
    vi.useRealTimers()
  })

  function sent(path: string) {
    return server.requests.filter((request) => request.path === path)
  }

  describe('the strip', () => {
    it("asks for the shown file's strip with the setting's count and shows its first frame", async () => {
      const { preview } = await shown()
      const asked = sent('/api/preview/frames')
      expect(asked).toHaveLength(1)
      expect(asked[0]!.body).toEqual({ source_id: 'movie' })
      expect(preview.strip).toHaveLength(10)
      expect(preview.index).toBe(0)
      expect(preview.current?.timestamp).toBe(0.2)
      expect(preview.current?.url).toBe(
        'http://server/api/preview/frames/movie-200-source.png?exp=1&sig=s',
      )
    })

    it('asks nothing and shows nothing while no file is shown', async () => {
      const preview = usePreviewStore()
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/frames')).toHaveLength(0)
      expect(preview.sourceId).toBeNull()
      expect(preview.current).toBeNull()
    })

    it('asks again when the number of sample frames changes', async () => {
      const settings = useSettingsStore()
      settings.settings = { preview: { sample_frames: 10, cache_size_mb: 1024 } } as AppSettings
      const { preview } = await shown()
      expect(sent('/api/preview/frames')).toHaveLength(1)
      settings.settings = { preview: { sample_frames: 4, cache_size_mb: 1024 } } as AppSettings
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/frames')).toHaveLength(2)
      expect(preview.strip).toHaveLength(10)
    })

    it("shows the problem's title when the strip fails, and the strip after a reload", async () => {
      server.on('POST /api/preview/frames', () =>
        problem(422, 'preview.failed', 'FFmpeg could not decode the file'),
      )
      const { preview } = await shown()
      expect(preview.error).toBe('FFmpeg could not decode the file')
      expect(preview.strip).toEqual([])
      expect(preview.loading).toBe(false)

      server.on('POST /api/preview/frames', strip('movie'))
      await preview.reload()
      expect(preview.error).toBeNull()
      expect(preview.strip).toHaveLength(10)
      expect(preview.current?.timestamp).toBe(0.2)
    })

    it('asks for no strip and no output frame for a file without video', async () => {
      const source = { video: [], audio: [{}] } as unknown as MediaSource
      useSourcesStore().entries = [{ id: 'movie', path: '/media/movie.mka', source }]
      const { preview } = await shown()
      preview.panelOpen = true
      preview.viewMode = 'split'
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(preview.noVideo).toBe(true)
      expect(sent('/api/preview/frames')).toHaveLength(0)
      expect(sent('/api/preview/render')).toHaveLength(0)
      expect(preview.loading).toBe(false)
      expect(preview.error).toBeNull()
    })

    it('drops the strip when a new probe of the file finds no video', async () => {
      holdFrames = true
      const sources = useSourcesStore()
      sources.entries = [{ id: 'movie', path: '/media/movie.mkv', source: null }]
      const { preview } = await shown()
      expect(preview.loading).toBe(true)
      const source = { video: [], audio: [{}] } as unknown as MediaSource
      sources.entries = [{ id: 'movie', path: '/media/movie.mkv', source }]
      await vi.advanceTimersByTimeAsync(0)
      expect(
        signals.find((request) => request.path === '/api/preview/frames')!.signal.aborted,
      ).toBe(true)
      expect(sent('/api/preview/frames')).toHaveLength(1)
      expect(preview.loading).toBe(false)
    })

    it('keeps the HDR note of the answer', async () => {
      const note = 'The source is HDR10: a PNG cannot hold HDR, so the frames are tone mapped.'
      server.on('POST /api/preview/frames', { ...strip('movie'), notes: [note] })
      const { preview } = await shown()
      expect(preview.notes).toEqual([note])
    })
  })

  describe('moving through the frames', () => {
    it('selects and steps through the strip, and stops at its ends', async () => {
      const { preview } = await shown()
      preview.select(4)
      expect(preview.current?.timestamp).toBeCloseTo(1.8)
      preview.step(1)
      expect(preview.index).toBe(5)
      preview.step(-1)
      preview.step(-1)
      expect(preview.index).toBe(3)
      preview.select(9)
      preview.step(1)
      expect(preview.index).toBe(9)
      preview.select(0)
      preview.step(-1)
      expect(preview.index).toBe(0)
    })

    it('shows the frame of a seek, and steps from its time to the strip frames next to it', async () => {
      const { preview } = await shown()
      await preview.seek(2.5)
      expect(sent('/api/preview/frames')[1]!.body).toEqual({
        source_id: 'movie',
        timestamps: [2.5],
      })
      expect(preview.index).toBeNull()
      expect(preview.current?.timestamp).toBe(2.5)
      preview.step(1)
      expect(preview.current?.timestamp).toBeCloseTo(2.6)
      await preview.seek(2.5)
      preview.step(-1)
      expect(preview.current?.timestamp).toBeCloseTo(2.2)
    })

    it("shows the server's note for a time without a picture and keeps the frame", async () => {
      const note = 'No frame at 99.000 s: the file ends at 4.000 s.'
      const { preview } = await shown()
      preview.select(3)
      server.on('POST /api/preview/frames', { frames: [], notes: [note] })
      await preview.seek(99)
      expect(preview.seekNote).toBe(note)
      expect(preview.index).toBe(3)
      preview.select(4)
      expect(preview.seekNote).toBeNull()
    })

    it("shows the problem's title when a seek fails", async () => {
      const { preview } = await shown()
      server.on('POST /api/preview/frames', () => problem(422, 'preview.failed', 'It failed'))
      await preview.seek(1)
      expect(preview.seekNote).toBe('It failed')
      expect(preview.seeking).toBe(false)
    })

    it('shows only the newest of two seeks', async () => {
      const { preview } = await shown()
      holdFrames = true
      const first = preview.seek(1)
      const second = preview.seek(3)
      await vi.advanceTimersByTimeAsync(0)
      frames[1]!.resolve({ frames: [frame('movie', 3)], notes: [] })
      await second
      frames[0]!.resolve({ frames: [frame('movie', 1)], notes: [] })
      await first
      expect(preview.current?.timestamp).toBe(3)
    })
  })

  describe('another file', () => {
    it('aborts every request of the last file and drops its frames', async () => {
      const { editor, preview } = await shown()
      holdFrames = true
      void preview.seek(1)
      void preview.reload()
      await vi.advanceTimersByTimeAsync(0)
      const last = signals.filter((request) => request.path === '/api/preview/frames').slice(-2)
      expect(last.map((request) => request.signal.aborted)).toEqual([false, false])

      await editor.open('other')
      await vi.advanceTimersByTimeAsync(0)
      expect(last.map((request) => request.signal.aborted)).toEqual([true, true])
      expect(preview.strip).toEqual([])
      expect(preview.current).toBeNull()
      expect(preview.loading).toBe(true)
      const asked = sent('/api/preview/frames').at(-1)!
      expect(asked.body).toEqual({ source_id: 'other' })

      // An answer for the last file that still comes is not shown.
      frames[0]!.resolve({ frames: [frame('movie', 1)], notes: [] })
      frames[1]!.resolve(strip('movie'))
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.current).toBeNull()
      frames[2]!.resolve(strip('other'))
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.current?.key).toBe('other-200-source')
    })

    it('aborts the render of the last file and drops its output frame and notes', async () => {
      const { editor, preview } = await shown()
      preview.panelOpen = true
      preview.viewMode = 'output'
      await vi.advanceTimersByTimeAsync(0)
      renders[0]!.resolve(
        renderAnswer(sent('/api/preview/render')[0]!.body as RenderBody, ['Copied video.']),
      )
      await vi.advanceTimersByTimeAsync(0)
      preview.select(1)
      await vi.advanceTimersByTimeAsync(0)
      const render = signals.filter((request) => request.path === '/api/preview/render')[1]!
      await editor.open('other')
      expect(render.signal.aborted).toBe(true)
      expect(preview.output).toBeNull()
      expect(preview.renderNotes).toEqual([])
      // Nothing is rendered until the new file has a frame.
      holdFrames = true
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(sent('/api/preview/render')).toHaveLength(2)
      expect(preview.renderError).toBeNull()
    })
  })

  describe('the output frame', () => {
    it('is asked for only while the panel is open and its view needs one', async () => {
      const { preview } = await shown()
      preview.viewMode = 'split'
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(sent('/api/preview/render')).toHaveLength(0)
      preview.panelOpen = true
      preview.viewMode = 'source'
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(sent('/api/preview/render')).toHaveLength(0)
      preview.viewMode = 'output'
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/render')).toHaveLength(1)
    })

    it("renders the job at the current frame's time and shows the output frame", async () => {
      const { preview } = await rendering()
      const body = sent('/api/preview/render')[0]!.body as RenderBody
      expect(body.timestamp).toBe(0.2)
      expect(body.job.source.path).toBe('/media/movie.mkv')
      expect(preview.rendering).toBe(true)
      renders[0]!.resolve(renderAnswer(body, ['Burned-in subtitles are not drawn.']))
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.output?.kind).toBe('output')
      expect(preview.output?.url).toMatch(/^http:\/\/server\/api\/preview\/frames\/out/)
      expect(preview.renderNotes).toEqual(['Burned-in subtitles are not drawn.'])
      expect(preview.rendering).toBe(false)
    })

    it('asks again at once for another frame', async () => {
      const { preview } = await rendering()
      preview.select(2)
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/render')).toHaveLength(2)
      expect((sent('/api/preview/render')[1]!.body as RenderBody).timestamp).toBeCloseTo(1)
    })

    it('follows an edit 250 ms after the last one, and shows only the newest answer', async () => {
      const { editor, preview } = await rendering()
      const first = sent('/api/preview/render')[0]!.body as RenderBody
      renders[0]!.resolve(renderAnswer(first))
      await vi.advanceTimersByTimeAsync(0)

      editor.set('/dimensions/size', { mode: 'width', width: 1280 })
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.output).toBeNull()
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 1)
      expect(sent('/api/preview/render')).toHaveLength(1)
      await vi.advanceTimersByTimeAsync(1)
      expect(sent('/api/preview/render')).toHaveLength(2)

      editor.set('/dimensions/size', { mode: 'width', width: 640 })
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(sent('/api/preview/render')).toHaveLength(3)
      const renderSignals = signals.filter((request) => request.path === '/api/preview/render')
      expect(renderSignals[1]!.signal.aborted).toBe(true)

      renders[2]!.resolve(renderAnswer(sent('/api/preview/render')[2]!.body as RenderBody))
      await vi.advanceTimersByTimeAsync(0)
      renders[1]!.resolve(renderAnswer(sent('/api/preview/render')[1]!.body as RenderBody))
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.output?.width).toBe(640)
    })

    it('is not asked again for an edit that does not change the picture', async () => {
      const { editor } = await rendering()
      editor.set('/audio/0/bitrate', 192)
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE * 2)
      expect(sent('/api/preview/render')).toHaveLength(1)
    })

    it('shows the note of a job FFmpeg refused', async () => {
      const { preview } = await rendering()
      const note = 'No output frame at 0.200 s: FFmpeg failed (exit code 234).'
      renders[0]!.resolve({ frames: [frame('movie', 0.2)], notes: [note] })
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.output).toBeNull()
      expect(preview.renderError).toBe(note)
    })

    it("shows the problem's title when the render fails", async () => {
      const { preview } = await rendering()
      renders[0]!.resolve(problem(422, 'preview.failed', 'The job cannot be planned'))
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.renderError).toBe('The job cannot be planned')
      expect(preview.rendering).toBe(false)
    })

    it('renders again on request after a failure, and shows the new answer', async () => {
      const { preview } = await rendering()
      renders[0]!.resolve(problem(422, 'preview.failed', 'The job cannot be planned'))
      await vi.advanceTimersByTimeAsync(0)
      preview.renderAgain()
      expect(preview.renderError).toBeNull()
      expect(preview.rendering).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/render')).toHaveLength(2)
      renders[1]!.resolve(renderAnswer(sent('/api/preview/render')[1]!.body as RenderBody))
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.output?.kind).toBe('output')
    })
  })

  describe('a frame image that did not load', () => {
    it('asks for the strip again once, and again after another frame is chosen', async () => {
      const { preview } = await shown()
      expect(preview.imageFailed(preview.strip[3]!)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/frames')).toHaveLength(2)
      expect(preview.imageFailed(preview.strip[0]!)).toBe(false)
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/frames')).toHaveLength(2)

      preview.select(1)
      expect(preview.imageFailed(preview.strip[1]!)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/frames')).toHaveLength(3)
    })

    it('asks for the strip again at a second expiry once a new link has loaded', async () => {
      const { preview } = await shown()
      expect(preview.imageFailed(preview.strip[3]!)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      preview.imageLoaded(preview.strip[3]!)
      expect(preview.imageFailed(preview.strip[3]!)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/frames')).toHaveLength(3)
    })

    it('asks for the frame of a seek again at a second expiry once a new link has loaded', async () => {
      const { preview } = await shown()
      await preview.seek(2.5)
      expect(preview.imageFailed(preview.current!)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.imageFailed(preview.current!)).toBe(false)
      preview.imageLoaded(preview.current!)
      expect(preview.imageFailed(preview.current!)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/frames')).toHaveLength(4)
    })

    it('asks for the frame of a seek again', async () => {
      const { preview } = await shown()
      await preview.seek(2.5)
      expect(preview.imageFailed(preview.current!)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      const asked = sent('/api/preview/frames')
      expect(asked).toHaveLength(3)
      expect(asked[2]!.body).toEqual({ source_id: 'movie', timestamps: [2.5] })
    })

    it('renders the output frame again', async () => {
      const { preview } = await shown()
      preview.panelOpen = true
      preview.viewMode = 'output'
      await vi.advanceTimersByTimeAsync(0)
      renders[0]!.resolve(renderAnswer(sent('/api/preview/render')[0]!.body as RenderBody))
      await vi.advanceTimersByTimeAsync(0)
      const broken = preview.output!
      expect(preview.imageFailed(broken)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/render')).toHaveLength(2)
      expect(preview.imageFailed(broken)).toBe(false)
    })

    it('renders the output frame again at a second expiry once a new link has loaded', async () => {
      const { preview } = await shown()
      preview.panelOpen = true
      preview.viewMode = 'output'
      await vi.advanceTimersByTimeAsync(0)
      renders[0]!.resolve(renderAnswer(sent('/api/preview/render')[0]!.body as RenderBody))
      await vi.advanceTimersByTimeAsync(0)
      expect(preview.imageFailed(preview.output!)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      renders[1]!.resolve(renderAnswer(sent('/api/preview/render')[1]!.body as RenderBody))
      await vi.advanceTimersByTimeAsync(0)
      preview.imageLoaded(preview.output!)
      expect(preview.imageFailed(preview.output!)).toBe(true)
      await vi.advanceTimersByTimeAsync(0)
      expect(sent('/api/preview/render')).toHaveLength(3)
    })
  })
})
