import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { JobSettings, ValidationIssue } from '@/api/types'
import SummaryTab from '@/components/editor/tabs/SummaryTab.vue'
import { mountShell } from '@/components/shell/testing'
import { issue, sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import { forgetThumbnails } from './useThumbnail'
import { multitrackSource, sampleDefinitions } from './testing'

// The naming editor is tested on its own; here it would need a complete naming preview.
vi.mock('@/components/naming/JobNamingEditor.vue', () => ({
  default: { name: 'JobNamingEditor', render: () => null },
}))

const SOON = { timeout: 2000, interval: 20 }

/** `jobs/geometry` as the server computes it for the job's dimensions (320×180, no crop). */
function geometryFor(job: JobSettings) {
  const size = job.dimensions?.size
  const width = size?.mode === 'width' ? size.width : 320
  const height = Math.round((width * 180) / 320)
  return {
    source: { width: 320, height: 180, rotation: 0, chroma_step_x: 2, chroma_step_y: 2 },
    geometry: job.video?.passthrough
      ? null
      : {
          crop: { top: 0, bottom: 0, left: 0, right: 0 },
          cropped_width: 320,
          cropped_height: 180,
          scaled_width: width,
          scaled_height: height,
          output_sar: { num: 1, den: 1 },
          display_aspect: 16 / 9,
          rotation: 0,
          upscaled: width > 320,
          notes: [],
        },
  }
}

const mounted: VueWrapper[] = []

beforeAll(() => {
  // jsdom lays nothing out; a revealed field scrolls itself into view.
  Element.prototype.scrollIntoView = () => {}
})

beforeEach(() => {
  forgetThumbnails()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

let server: FakeServer

async function mountSummary(options: { entry?: boolean; issues?: ValidationIssue[] } = {}) {
  server = new FakeServer()
    .on('POST /api/jobs/draft', () => {
      const draft = sampleDraft()
      draft.naming = {
        ...draft.naming,
        source: 'file',
        reason: 'File name: 1 field recognised (1 point)',
      }
      return draft
    })
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
    .on('POST /api/jobs/geometry', (request) =>
      geometryFor((request.body as { job: JobSettings }).job),
    )
    .on('POST /api/jobs/type', {
      job_type: 'encode',
      reason: 'Encode: the video is encoded with x265.',
      in_place_blockers: ['the video is encoded'],
    })
    .on('POST /api/preview/frames', {
      frames: [
        {
          key: 'k',
          kind: 'source',
          timestamp: 2,
          width: 320,
          height: 180,
          cached: true,
          url: '/api/preview/frames/k.png?exp=1&sig=s',
        },
      ],
      notes: [],
    })
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const { wrapper } = await mountShell(SummaryTab, {
    setup() {
      useSystemStore().definitions = sampleDefinitions()
      if (options.entry !== false) {
        useSourcesStore().entries = [
          { id: 'src', path: '/media/multitrack.mkv', source: multitrackSource() },
        ]
      }
    },
  })
  mounted.push(wrapper)
  const editor = useEditorStore()
  await editor.open('src')
  useValidationStore().issues = options.issues ?? []
  await flushPromises()
  return { wrapper, editor }
}

function text(wrapper: VueWrapper, selector: string): string {
  return wrapper.find(selector).text().replace(/\s+/g, ' ').trim()
}

describe('the Summary tab', () => {
  it('shows every card for the multitrack fixture', async () => {
    const { wrapper } = await mountSummary()
    expect(wrapper.findAll('[data-card]').map((card) => card.attributes('data-card'))).toEqual([
      'source',
      'job-type',
      'output',
      'picture',
      'video',
      'tracks',
      'issues',
      'estimate',
    ])
    expect(wrapper.find('[data-card="source"] img').attributes('src')).toBe(
      'http://server/api/preview/frames/k.png?exp=1&sig=s',
    )
    expect(text(wrapper, '[data-card="source"]')).toContain('Size370 KiB')
    expect(text(wrapper, '[data-field="video-line"]')).toBe(
      'H.264 Constrained Baseline · 320×180 · 25 fps',
    )
    expect(text(wrapper, '[data-field="tracks"]')).toBe('3 audio tracks · 3 subtitle tracks')
    await vi.waitFor(
      () =>
        expect(text(wrapper, '[data-field="pipeline"]')).toBe('320×180 · 1.78:1 · square pixels'),
      SOON,
    )
    expect(text(wrapper, '[data-field="filters"]')).toContain('Deinterlace: Default')
    expect(text(wrapper, '[data-field="encoder"]')).toBe('x265')
    expect(text(wrapper, '[data-field="quality"]')).toBe('Constant quality RF 22')
    expect(text(wrapper, '[data-field="speed"]')).toBe('Slow')
    expect(wrapper.findAll('[data-group="audio"] [data-path]')).toHaveLength(3)
    expect(wrapper.findAll('[data-group="subtitles"] [data-path]')).toHaveLength(1)
    expect(text(wrapper, '[data-card="estimate"] [data-field="size"]')).toBe('Depends on content')
  })

  it('nests its headings under the tab, one level at a time', async () => {
    const { wrapper } = await mountSummary()
    const levels = [...wrapper.element.querySelectorAll('h1, h2, h3, h4, h5, h6')].map((heading) =>
      Number(heading.tagName.slice(1)),
    )
    expect(levels[0]).toBe(2)
    expect(levels.every((level, index) => index === 0 || level <= levels[index - 1]! + 1)).toBe(
      true,
    )
  })

  it('updates every card as the job changes, through undo and redo', async () => {
    const { wrapper, editor } = await mountSummary()
    editor.set('/video/rate_control', {
      mode: 'bitrate',
      kbps: 6000,
      two_pass: true,
      turbo_first_pass: false,
    })
    await flushPromises()
    expect(text(wrapper, '[data-card="estimate"] [data-field="size"]')).toBe('About 3.1 MiB')
    expect(text(wrapper, '[data-field="quality"]')).toBe('Average bitrate 6000 kb/s · 2-pass')
    editor.undo()
    await flushPromises()
    expect(text(wrapper, '[data-card="estimate"] [data-field="size"]')).toBe('Depends on content')
    editor.redo()
    await flushPromises()
    expect(text(wrapper, '[data-card="estimate"] [data-field="size"]')).toBe('About 3.1 MiB')

    editor.patch([
      { op: 'replace', path: '/video/encoder', value: 'hevc_nvenc' },
      { op: 'replace', path: '/video/preset', value: 'p5' },
      { op: 'add', path: '/video/advanced/bframes', value: 3 },
      { op: 'remove', path: '/audio/2' },
      { op: 'replace', path: '/output/container', value: 'mp4' },
    ])
    await flushPromises()
    expect(text(wrapper, '[data-field="encoder"]')).toBe('NVIDIA NVENC H.265')
    expect(text(wrapper, '[data-field="speed"]')).toBe('P5 (slow)')
    expect(text(wrapper, '[data-field="advanced"]')).toBe('1 changed')
    expect(wrapper.findAll('[data-group="audio"] [data-path]')).toHaveLength(2)
    expect(wrapper.find('[data-field="web-optimized"]').exists()).toBe(true)

    editor.set('/dimensions/size', { mode: 'width', width: 1280 })
    await vi.waitFor(
      () => expect(text(wrapper, '[data-field="pipeline"]')).toContain('scale 1280×720'),
      SOON,
    )
    expect(wrapper.find('.summary-picture__pipeline--warn').exists()).toBe(true)
  })

  it('writes the container and the output options through the editor, one undo step each', async () => {
    const { wrapper, editor } = await mountSummary()
    expect(wrapper.find('[data-field="web-optimized"]').exists()).toBe(false)
    const mp4 = wrapper.findAll('[data-field="container"] button').find((b) => b.text() === 'MP4')
    await mp4!.trigger('click')
    expect(editor.job?.output?.container).toBe('mp4')
    expect(wrapper.find('[data-field="web-optimized"]').exists()).toBe(true)
    await wrapper.find('[data-field="align-av-start"] input').trigger('change')
    expect(editor.job?.output?.align_av_start).toBe(true)
    editor.undo()
    expect(editor.job?.output?.align_av_start).toBe(false)
    expect(editor.job?.output?.container).toBe('mp4')
    editor.undo()
    await flushPromises()
    expect(editor.job?.output?.container).toBe('mkv')
    expect(wrapper.find('[data-field="web-optimized"]').exists()).toBe(false)
  })

  it('opens the track of a chip and the field of a video line on their tabs', async () => {
    const { wrapper } = await mountSummary()
    const ui = useUiStore()
    await wrapper.find('[data-card="tracks"] [data-path="audio[1]"]').trigger('click')
    expect(ui.activeTab).toBe('audio')
    expect(ui.revealed?.path).toBe('audio[1]')
    await wrapper.find('[data-card="tracks"] [data-path="subtitles[0]"]').trigger('click')
    expect(ui.activeTab).toBe('subtitles')
    expect(ui.revealed?.path).toBe('subtitles[0]')
    await wrapper
      .find('[data-card="video"] button[data-path="video.rate_control"]')
      .trigger('click')
    expect(ui.activeTab).toBe('video')
    expect(ui.revealed?.path).toBe('video.rate_control')
  })

  it('links the Picture card to the Dimensions and the Filters tab', async () => {
    const { wrapper } = await mountSummary()
    await wrapper.find('[data-field="filters"] button').trigger('click')
    expect(useUiStore().activeTab).toBe('filters')
  })

  it('groups the issues by severity with their fix buttons, and a fix changes the job', async () => {
    const fix = {
      label: 'Use libx264 (closest match)',
      patch: [{ op: 'replace' as const, path: '/video/encoder', value: 'libx264' }],
      target: 'job' as const,
    }
    const { wrapper, editor } = await mountSummary({
      issues: [
        issue('crop.note', 'dimensions.crop', 'info'),
        issue('encoder.untested', 'video.encoder', 'warning'),
        issue('encoder.unavailable', 'video.encoder', 'error', [fix]),
        issue('audio.bitrate', 'audio[1].bitrate', 'warning'),
      ],
    })
    const groups = wrapper.findAll('[data-card="issues"] section[data-severity]')
    expect(groups.map((group) => group.attributes('data-severity'))).toEqual([
      'error',
      'warning',
      'info',
    ])
    expect(groups.map((group) => group.findAll('li').length)).toEqual([1, 2, 1])
    expect(groups[1]!.find('h4').text()).toBe('Warnings (2)')
    expect(wrapper.find('[data-path="audio[1]"]').classes()).toContain('summary-track--warning')

    await groups[0]!.find('.rf-issue__fix').trigger('click')
    await flushPromises()
    expect(editor.job?.video?.encoder).toBe('libx264')
    expect(text(wrapper, '[data-field="encoder"]')).toBe('x264')
    editor.undo()
    await flushPromises()
    expect(text(wrapper, '[data-field="encoder"]')).toBe('x265')

    await groups[0]!.find('.rf-issue__reveal').trigger('click')
    expect(useUiStore().activeTab).toBe('video')
  })

  it('works for a job loaded back from the queue, which has no draft', async () => {
    const { wrapper, editor } = await mountSummary()
    editor.draft = null
    editor.target = { kind: 'job', sourceId: 'src', job: sampleJob() }
    await flushPromises()
    expect(wrapper.findAll('[data-card]')).toHaveLength(8)
    expect(text(wrapper, '[data-field="encoder"]')).toBe('x265')
  })

  it('says when the source is not open, and still shows the job', async () => {
    const { wrapper } = await mountSummary({ entry: false })
    expect(wrapper.find('[data-state="not-probed"]').text()).toContain('not open')
    expect(text(wrapper, '[data-field="file"]')).toBe('multitrack.mkv')
    expect(server.count('POST /api/preview/frames')).toBe(0)
    expect(wrapper.findAll('[data-group="audio"] [data-path]')).toHaveLength(3)
  })
})
