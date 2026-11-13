import { FakeServer, type Recorded } from '@/api/testing/fakes'
import type {
  BatchGroup,
  JobDraft,
  JobTemplate,
  JsonPatchOp,
  MediaSource,
  Resolution,
} from '@/api/types'
import { multitrackSource } from '@/components/summary/testing'
import { applyOps } from '@/editor/patch'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'

/** chapters.mkv as ffprobe gives it: 5.021 s, H.264 at 25/1 fps, four named chapters. */
export function chaptersSource(): MediaSource {
  const source = multitrackSource()
  source.container = { ...source.container, duration: 5.021 }
  const video = source.video![0]!
  source.video = [
    { ...video, duration: null, frame_count: null, avg_frame_rate: { num: 25, den: 1 } },
  ]
  source.chapters = [
    { index: 0, start: 0, end: 1, title: 'Opening' },
    { index: 1, start: 1, end: 2.5, title: 'Part One' },
    { index: 2, start: 2.5, end: 4, title: 'Part Two' },
    { index: 3, start: 4, end: 5, title: 'Credits' },
  ]
  return source
}

/** A source whose video says no frame rate, and that has no chapters. */
export function bareSource(): MediaSource {
  const source = chaptersSource()
  source.chapters = []
  source.video = [{ ...source.video![0]!, avg_frame_rate: null, frame_rate: null }]
  return source
}

const PRESET = 'h265-mkv-1080p'

type ResolveBody = {
  template: JobTemplate
  source_ids: string[]
  overrides?: Record<string, JsonPatchOp[]>
}

/** A file of `/media/<id>.mkv`: the template's video, then the `/job` part of its override. */
function row(template: JobTemplate, id: string, override: JsonPatchOp[] = []): Resolution {
  let job = sampleJob()
  job.source.path = `/media/${id}.mkv`
  job.video = { ...template.video!, metadata: job.video!.metadata }
  const own: JsonPatchOp[] = []
  for (const op of override) {
    if (op.path.startsWith('/job/')) own.push({ ...op, path: op.path.slice(4) })
  }
  job = applyOps(job, own)
  return { path: job.source.path, job, matches: [], issues: [], status: 'ok', override }
}

function rows(request: Recorded): Resolution[] {
  const { template, source_ids, overrides } = request.body as ResolveBody
  return source_ids.map((id) => row(template, id, overrides?.[id]))
}

/** The group of `/media/e1.mkv` and `/media/e2.mkv`. */
export function rangeGroup(): BatchGroup {
  return {
    id: 'g1',
    name: 'Show S01',
    level: 'standard',
    representative: '/media/e1.mkv',
    fingerprint: { level: 'standard', tracks: [], digest: 'd' },
    members: ['e1', 'e2'].map((id, index) => ({
      path: `/media/${id}.mkv`,
      match: 'exact',
      episode: index + 1,
    })),
  }
}

/** Drafts `/media/<source id>.mkv` and resolves the group's files. */
export function rangeServer(): FakeServer {
  return new FakeServer()
    .on('POST /api/jobs/draft', (request): JobDraft => {
      const job = sampleJob()
      job.source.path = `/media/${(request.body as { source_id: string }).source_id}.mkv`
      return sampleDraft(job)
    })
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets', { presets: [samplePreset()], default_id: PRESET })
    .on(`GET /api/presets/${PRESET}`, samplePreset())
    .on('POST /api/batch/resolve', (request) => ({ columns: [], rows: rows(request), issues: [] }))
    .on('POST /api/batch/resolve-run', (request) => ({
      grouping: { groups: [], issues: [] },
      resolutions: [{ columns: [], rows: rows(request), issues: [] }],
    }))
}
