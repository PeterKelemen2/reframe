// Test data of the crop store and the Dimensions tab: `letterbox.mkv` as the real server
// describes it (320×180 4:2:0, detection 22 / 24 / 0 / 0 on 5 of 10 frames, conservative none),
// and an editor on a fake server whose `jobs/draft` gives the sample job in automatic crop.
import { createPinia, setActivePinia } from 'pinia'

import { configureClient } from '@/api/client'
import { type Deferred, deferred, FakeServer } from '@/api/testing/fakes'
import type { CropDetection, JobGeometry, JobSettings, SourceGeometry, TaskInfo } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { useTasksStore } from '@/stores/tasks'

export const LETTERBOX: SourceGeometry = {
  width: 320,
  height: 180,
  sar: { num: 1, den: 1 },
  rotation: 0,
  chroma_step_x: 2,
  chroma_step_y: 2,
  interlaced: false,
  chroma_assumed: false,
}

export function geometryOf(
  source: SourceGeometry = LETTERBOX,
  geometry: Partial<NonNullable<JobGeometry['geometry']>> = {},
): JobGeometry {
  return {
    source,
    geometry: {
      crop: { top: 0, bottom: 0, left: 0, right: 0 },
      cropped_width: source.width,
      cropped_height: source.height,
      scaled_width: source.width,
      scaled_height: source.height,
      output_sar: { num: 1, den: 1 },
      display_aspect: source.width / source.height,
      rotation: 0,
      upscaled: false,
      notes: [],
      filter_rotation: 0,
      flip_horizontal: false,
      ...geometry,
    },
  }
}

/** `text` with the no-break space that keeps each crop edge's letter with its value (`T 22`). */
export function edgesText(text: string): string {
  return text.replaceAll(/\b([TBLR]) (\d)/g, '$1 $2')
}

const LETTERBOX_BARS = { top: 22, bottom: 24, left: 0, right: 0 }
const PILLARBOX_BARS = { top: 0, bottom: 0, left: 40, right: 40 }

export function letterboxDetection(): CropDetection {
  return {
    samples: [0.2, 0.6, 1, 1.4, 1.8, 2.2, 2.6, 3, 3.4, 3.8].map((timestamp, index) => ({
      timestamp,
      crop: index < 5 ? { ...LETTERBOX_BARS } : { ...PILLARBOX_BARS },
    })),
    auto: { ...LETTERBOX_BARS },
    auto_frames: 5,
    conservative: { top: 0, bottom: 0, left: 0, right: 0 },
    notes: [],
  }
}

export interface CropServer {
  server: FakeServer
  /** One per `preview/cropdetect` request, in order; resolve it to answer. */
  detections: Deferred<void>[]
  /** What the task of each detection ends as (its id is `crop-<n>`). */
  outcome: { task: Partial<TaskInfo> }
}

/**
 * A fresh Pinia and a fake server: `jobs/draft` answers `job` for every file (its path is the
 * file's), `jobs/geometry` answers `geometry`, and each crop detection is a task that ends as
 * `outcome.task` once the test resolves its entry of `detections`.
 */
export function setUpCrop(
  options: { job?: JobSettings; geometry?: JobGeometry } = {},
): CropServer & { pinia: ReturnType<typeof createPinia> } {
  const pinia = createPinia()
  setActivePinia(pinia)
  const job = options.job ?? sampleJob()
  const detections: Deferred<void>[] = []
  const outcome: CropServer['outcome'] = {
    task: { state: 'done', result: letterboxDetection() as never },
  }
  const tasks = useTasksStore()
  const server = new FakeServer()
    .on('POST /api/jobs/draft', (request) => {
      const draft = structuredClone(job)
      draft.source.path = `/media/${(request.body as { source_id: string }).source_id}.mkv`
      return sampleDraft(draft)
    })
    .on('POST /api/presets/diff', [])
    .on(`GET /api/presets/${job.preset_id}`, { ...samplePreset(), id: job.preset_id })
    .on('POST /api/jobs/validate', { issues: [] })
    .on('POST /api/jobs/geometry', options.geometry ?? geometryOf())
    .on('POST /api/preview/cropdetect', async () => {
      const answer = deferred<void>()
      detections.push(answer)
      const id = `crop-${detections.length}`
      await answer.promise
      tasks.tasks[id] = { id, kind: 'cropdetect', ...outcome.task } as TaskInfo
      return { task_id: id }
    })
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  return { pinia, server, detections, outcome }
}
