import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { FrameLink, Frames } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'

export function frameLink(
  timestamp: number,
  kind: FrameLink['kind'] = 'source',
  size = { width: 320, height: 180 },
): FrameLink {
  const key = `movie-${Math.round(timestamp * 1000)}-${kind}`
  return { key, kind, timestamp, ...size, cached: false, url: `/frames/${key}.png` }
}

/** A server that drafts any source and answers a strip of ten frames and every render. */
export function previewServer(): FakeServer {
  const server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(sampleJob()))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
    .on('POST /api/preview/frames', (request): Frames => {
      const timestamps = (request.body as { timestamps?: number[] }).timestamps
      const times = timestamps ?? Array.from({ length: 10 }, (_, at) => 0.2 + at * 0.4)
      return { frames: times.map((t) => frameLink(t)), notes: [] }
    })
    .on('POST /api/preview/render', (request): Frames => {
      const timestamp = (request.body as { timestamp: number }).timestamp
      return {
        frames: [frameLink(timestamp), frameLink(timestamp, 'output', { width: 640, height: 268 })],
        notes: [],
      }
    })
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  return server
}
