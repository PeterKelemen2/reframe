import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { problem, type FakeServer } from '@/api/testing/fakes'
import type { FrameLink, Frames, JobSettings, PreviewClip } from '@/api/types'
import { geometryOf, LETTERBOX } from '@/components/dimensions/testing'
import SplitCompare from '@/components/media/SplitCompare.vue'
import { frameLink, previewServer } from '@/components/preview/testing'
import { mountShell } from '@/components/shell/testing'
import { sampleJob } from '@/editor/testing/samples'
import { useClipsStore } from '@/stores/clips'

import ClipCompare from './ClipCompare.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

const CLIP: PreviewClip = {
  id: 'clip-1',
  start: 0.2,
  duration: 3,
  container: 'mkv',
  video_codec: 'hevc',
  size: 2048,
}

function clipFrame(timestamp: number): FrameLink {
  const key = `clip-${Math.round(timestamp * 1000)}`
  return { ...frameLink(timestamp), key, url: `/frames/${key}.png` }
}

function clipFrames(server: FakeServer, id = 'clip-1', leaveOut: number[] = []): void {
  server.on(`POST /api/preview/clips/${id}/frames`, (request): Frames => {
    const times = (request.body as { timestamps: number[] }).timestamps
    return {
      frames: times.filter((time) => !leaveOut.includes(time)).map(clipFrame),
      notes: leaveOut.map((time) => `No frame at ${time} s`),
    }
  })
}

const BARS = { top: 22, bottom: 24, left: 0, right: 0 }

/** The job the clip was made from: the letterbox bars cropped. */
function madeFrom(): JobSettings {
  const job = sampleJob()
  job.dimensions = { ...job.dimensions!, crop: { mode: 'auto', rect: BARS } }
  return job
}

async function compare(setup?: (server: FakeServer) => void) {
  const server = previewServer()
  clipFrames(server)
  server.on('POST /api/jobs/geometry', (request) => {
    const { job } = request.body as { job: JobSettings }
    return geometryOf(LETTERBOX, { crop: job.dimensions?.crop?.rect ?? undefined })
  })
  setup?.(server)
  const { wrapper } = await mountShell(ClipCompare, {
    props: { clip: CLIP, sourceId: 'movie', job: madeFrom() },
  })
  mounted.push(wrapper)
  await flushPromises()
  const split = () => wrapper.findComponent(SplitCompare)
  return { wrapper, server, split }
}

function bodyOf(server: FakeServer, path: string): unknown {
  return server.requests.findLast((request) => request.path === path)?.body
}

describe('the frame compare of a clip', () => {
  it('shows evenly spaced clip frames next to the source frames at the same times', async () => {
    const { server, split, wrapper } = await compare()
    expect(bodyOf(server, '/api/preview/clips/clip-1/frames')).toEqual({
      timestamps: [0.3, 0.9, 1.5, 2.1, 2.7],
    })
    expect(bodyOf(server, '/api/preview/frames')).toEqual({
      source_id: 'movie',
      timestamps: [0.5, 1.1, 1.7, 2.3, 2.9],
    })
    expect(split().props('before').url).toBe('http://server/frames/movie-500-source.png')
    expect(split().props('after').url).toBe('http://server/frames/clip-300.png')
    expect(wrapper.find('[data-field="compare-position"]').text()).toBe('Frame 1 of 5 · 0.5 s')
  })

  it('calls the two pictures the source and the encoded preview', async () => {
    const { wrapper, split } = await compare()
    expect(split().props('beforeLabel')).toBe('Source')
    expect(split().props('afterLabel')).toBe('Encoded preview')
    const labels = wrapper.findAll('.split-compare__label').map((label) => label.text())
    expect(labels).toEqual(['Source', 'Encoded preview'])
  })

  it('zooms the pictures to fit, 100 % and 200 % of the clip frame, scrolling inside its stage', async () => {
    const { wrapper, split } = await compare()
    const stage = wrapper.find('[data-field="compare-stage"]')
    expect(stage.find('.split-compare').element).toBe(split().element)
    expect(split().attributes('style')).toContain('width: min(100%, 106.66')
    const zoom = (label: string) =>
      wrapper
        .findAll('[data-field="compare-zoom"] [role="button"], [data-field="compare-zoom"] button')
        .find((option) => option.text() === label)
    await zoom('100 %')?.trigger('click')
    expect(split().attributes('style')).toContain('width: 320px')
    expect(stage.attributes('tabindex')).toBe('0')
    await zoom('200 %')?.trigger('click')
    expect(split().attributes('style')).toContain('width: 640px')
    await zoom('Fit')?.trigger('click')
    expect(stage.attributes('tabindex')).toBe('-1')
  })

  it('keeps the zoom when it steps to another frame', async () => {
    const { wrapper, split } = await compare()
    useClipsStore().zoom = 2
    await flushPromises()
    await wrapper.find('[data-action="compare-next"]').trigger('click')
    expect(split().attributes('style')).toContain('width: 640px')
  })

  it('crops the source frames as the job the clip was made from says', async () => {
    const { server, split } = await compare()
    expect(server.count('POST /api/jobs/geometry')).toBe(1)
    expect(bodyOf(server, '/api/jobs/geometry')).toEqual({ job: madeFrom() })
    expect(split().props('geometry')).toMatchObject({ crop: BARS })
  })

  it('steps through the times, round from the last to the first', async () => {
    const { split, wrapper } = await compare()
    await wrapper.find('[data-action="compare-previous"]').trigger('click')
    expect(split().props('after').url).toBe('http://server/frames/clip-2700.png')
    expect(split().props('before').url).toBe('http://server/frames/movie-2900-source.png')
    await wrapper.find('[data-action="compare-next"]').trigger('click')
    expect(wrapper.find('[data-field="compare-position"]').text()).toBe('Frame 1 of 5 · 0.5 s')
  })

  it('leaves out a time the clip gave no frame for, with its note', async () => {
    const { wrapper, split } = await compare((server) => clipFrames(server, 'clip-1', [0.3]))
    expect(wrapper.find('[data-field="compare-position"]').text()).toBe('Frame 1 of 4 · 1.1 s')
    expect(split().props('before').url).toBe('http://server/frames/movie-1100-source.png')
    expect(wrapper.find('[data-field="compare-notes"]').text()).toBe('No frame at 0.3 s')
  })

  it('shows why the frames could not be made, and tries again', async () => {
    const { wrapper, server } = await compare((fake) =>
      fake.on('POST /api/preview/clips/clip-1/frames', () =>
        problem(404, 'preview.unknown_clip', 'The clip is not in the cache'),
      ),
    )
    expect(wrapper.find('[data-state="compare-failed"]').text()).toContain(
      'The frames could not be compared: The clip is not in the cache',
    )
    clipFrames(server)
    await wrapper.find('[data-action="retry-compare"]').trigger('click')
    await flushPromises()
    expect(wrapper.findComponent(SplitCompare).exists()).toBe(true)
  })

  it('asks for the frames again once when an image fails, then says it failed', async () => {
    const { wrapper, server, split } = await compare()
    split().vm.$emit('failed', split().props('after'))
    await flushPromises()
    expect(server.count('POST /api/preview/clips/clip-1/frames')).toBe(2)
    expect(split().exists()).toBe(true)
    split().vm.$emit('failed', split().props('after'))
    await flushPromises()
    expect(server.count('POST /api/preview/clips/clip-1/frames')).toBe(2)
    expect(wrapper.find('[data-state="image-failed"]').exists()).toBe(true)
    clipFrames(server, 'clip-2')
    await wrapper.setProps({ clip: { ...CLIP, id: 'clip-2' } })
    await flushPromises()
    expect(split().exists()).toBe(true)
  })

  it('starts again at the first frame for another clip', async () => {
    const { wrapper, server } = await compare((fake) => clipFrames(fake, 'clip-2'))
    await wrapper.find('[data-action="compare-next"]').trigger('click')
    await wrapper.setProps({ clip: { ...CLIP, id: 'clip-2', start: 1, duration: 1 } })
    await flushPromises()
    expect(bodyOf(server, '/api/preview/clips/clip-2/frames')).toEqual({
      timestamps: [0.1, 0.3, 0.5, 0.7, 0.9],
    })
    expect(wrapper.find('[data-field="compare-position"]').text()).toBe('Frame 1 of 5 · 1.1 s')
  })
})
