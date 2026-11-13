import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { deferred, problem, type FakeServer } from '@/api/testing/fakes'
import type { FrameLink, JobSettings, PreviewClip as Clip, TaskInfo } from '@/api/types'
import { geometryOf, letterboxDetection } from '@/components/dimensions/testing'
import { previewServer } from '@/components/preview/testing'
import { mountShell } from '@/components/shell/testing'
import { platform } from '@/platform'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'
import { useTasksStore } from '@/stores/tasks'

import PreviewClip from './PreviewClip.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

const CLIP: Clip = {
  id: 'clip-1',
  start: 0.2,
  duration: 3,
  container: 'mkv',
  video_codec: 'hevc',
  size: 2048,
}

function clipFrame(timestamp: number): FrameLink {
  const key = `clip-${Math.round(timestamp * 1000)}`
  return {
    key,
    kind: 'source',
    timestamp,
    width: 320,
    height: 134,
    cached: false,
    url: `/frames/${key}.png`,
  }
}

async function panel(setup?: (server: FakeServer) => void) {
  const server = previewServer()
  let links = 0
  server
    .on('POST /api/preview/clip', { task_id: 't-1' })
    .on('GET /api/preview/clips/clip-1/link', () => {
      links += 1
      return { url: `/api/preview/clips/clip-1?sig=${links}` }
    })
    .on('POST /api/preview/clips/clip-1/frames', (request) => ({
      frames: (request.body as { timestamps: number[] }).timestamps.map(clipFrame),
      notes: [],
    }))
    .on('POST /api/tasks/t-1/cancel', () => new Response(null, { status: 204 }))
  setup?.(server)
  const { wrapper } = await mountShell(PreviewClip)
  mounted.push(wrapper)
  await useEditorStore().open('movie')
  await flushPromises()
  return { wrapper, server, tasks: useTasksStore() }
}

function end(task: Partial<TaskInfo>): void {
  useTasksStore().onTaskDone({
    type: 'task.done',
    task: { id: 't-1', kind: 'preview_clip', state: 'done', ...task },
  })
}

async function encoded(setup?: (server: FakeServer) => void) {
  const result = await panel(setup)
  await result.wrapper.find('[data-action="encode-clip"]').trigger('click')
  await flushPromises()
  end({ progress: 100, result: CLIP as never })
  await flushPromises()
  return result
}

function video(wrapper: VueWrapper) {
  return wrapper.find('[data-field="clip-video"]')
}

async function videoError(wrapper: VueWrapper, code: number): Promise<void> {
  const element = video(wrapper).element
  Object.defineProperty(element, 'error', { value: { code, message: 'Decoder gone' } })
  await video(wrapper).trigger('error')
  await flushPromises()
}

/** A crop detection that ends with the letterbox bars once the test resolves it. */
function detection(server: FakeServer) {
  const answer = deferred<void>()
  server.on('POST /api/preview/cropdetect', async () => {
    await answer.promise
    useTasksStore().tasks['crop-1'] = {
      id: 'crop-1',
      kind: 'cropdetect',
      state: 'done',
      result: letterboxDetection() as never,
    }
    return { task_id: 'crop-1' }
  })
  return answer
}

function sentJob(server: FakeServer): JobSettings | undefined {
  const sent = server.requests.find((request) => request.path === '/api/preview/clip')
  return (sent?.body as { job: JobSettings } | undefined)?.job
}

describe('the preview clip', () => {
  it('encodes the chosen length from the current frame with the editor job', async () => {
    const { wrapper, server } = await panel()
    usePreviewStore().select(2)
    await wrapper.find('[data-field="clip-length"]').findAll('button')[2]!.trigger('click')
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    const sent = server.requests.find((request) => request.path === '/api/preview/clip')
    expect(sent?.body).toEqual({ job: useEditorStore().job, start: 1, seconds: 30 })
  })

  it('waits for the crop detection of the file, then sends the job with the detected crop', async () => {
    let detected = deferred<void>()
    const { wrapper, server } = await panel((fake) => (detected = detection(fake)))
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    expect(server.count('POST /api/preview/clip')).toBe(0)
    expect(wrapper.find('[data-field="clip-status"]').text()).toBe(
      'Waiting for crop detection, so that the clip is cropped…',
    )
    detected.resolve()
    await flushPromises()
    expect(sentJob(server)?.dimensions?.crop).toEqual({
      mode: 'auto',
      rect: { top: 22, bottom: 24, left: 0, right: 0 },
    })
    end({ progress: 100, result: CLIP as never })
    await flushPromises()
    expect(wrapper.find('[data-field="clip-out-of-date"]').exists()).toBe(false)
  })

  it('sends nothing when Cancel comes while it waits for the crop detection', async () => {
    let detected = deferred<void>()
    const { wrapper, server } = await panel((fake) => (detected = detection(fake)))
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-action="cancel-clip"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-field="clip-cancelled"]').exists()).toBe(true)
    detected.resolve()
    await flushPromises()
    expect(server.count('POST /api/preview/clip')).toBe(0)
  })

  it('compares the frames with the geometry of the job the clip was made from', async () => {
    const { wrapper, server } = await encoded((fake) =>
      fake.on('POST /api/jobs/geometry', geometryOf()),
    )
    const sent = sentJob(server)
    useEditorStore().set('/dimensions/rotate', 90)
    const from = server.requests.length
    await wrapper.find('[data-action="compare-frames"]').trigger('click')
    await flushPromises()
    const asked = server.requests
      .slice(from)
      .filter((request) => request.path === '/api/jobs/geometry')
    expect(asked.map((request) => request.body)).toContainEqual({ job: sent })
  })

  it('shows the progress of the task, and Cancel cancels it', async () => {
    const { wrapper, server, tasks } = await panel()
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    tasks.onTaskProgress({
      type: 'task.progress',
      task: { id: 't-1', kind: 'preview_clip', state: 'running', progress: 42 },
    })
    await flushPromises()
    expect(wrapper.find('[data-field="clip-status"]').text()).toBe('Encoding the preview… 42 %')
    await wrapper.find('[data-action="cancel-clip"]').trigger('click')
    await flushPromises()
    expect(server.count('POST /api/tasks/t-1/cancel')).toBe(1)
    end({ state: 'cancelled' })
    await flushPromises()
    expect(wrapper.find('[data-field="clip-cancelled"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="encode-clip"]').exists()).toBe(true)
  })

  it('cancels the task as soon as the server names it when Cancel came first', async () => {
    const answer = deferred<unknown>()
    const { wrapper, server } = await panel((fake) =>
      fake.on('POST /api/preview/clip', () => answer.promise),
    )
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-action="cancel-clip"]').trigger('click')
    answer.resolve({ task_id: 't-1' })
    await flushPromises()
    expect(server.count('POST /api/tasks/t-1/cancel')).toBe(1)
    expect(wrapper.find('[data-field="clip-cancelled"]').exists()).toBe(true)
  })

  it('moves the focus from Encode to Cancel and back', async () => {
    const { wrapper } = await panel()
    ;(wrapper.find('[data-action="encode-clip"]').element as HTMLElement).focus()
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    expect(document.activeElement?.getAttribute('data-action')).toBe('cancel-clip')
    end({ state: 'cancelled' })
    await flushPromises()
    expect(document.activeElement?.getAttribute('data-action')).toBe('encode-clip')
  })

  it('shows the error of a failed task', async () => {
    const { wrapper } = await panel()
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    end({ state: 'failed', error: 'video.encoder_missing: libx265 is not there' })
    await flushPromises()
    expect(wrapper.find('[data-field="clip-error"]').text()).toBe(
      'The preview could not be encoded: video.encoder_missing: libx265 is not there',
    )
  })

  it('shows why the server refused the encode', async () => {
    const { wrapper } = await panel((fake) =>
      fake.on('POST /api/preview/clip', () => problem(403, 'fs.outside_roots', 'Not allowed')),
    )
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-field="clip-error"]').text()).toBe(
      'The preview could not be encoded: Not allowed',
    )
  })

  it('says so when the server no longer knows the task', async () => {
    const { wrapper, server, tasks } = await panel()
    server.on('GET /api/tasks', [])
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    await tasks.resync()
    await flushPromises()
    expect(wrapper.find('[data-field="clip-error"]').text()).toContain('t-1')
    expect(wrapper.find('[data-action="encode-clip"]').exists()).toBe(true)
  })

  it('plays the finished clip from its signed link on the server', async () => {
    const { wrapper } = await encoded()
    expect(wrapper.find('[data-field="clip-summary"]').text()).toBe('3 s from 0.2 s · hevc · 2 KiB')
    expect(video(wrapper).attributes('src')).toBe('http://server/api/preview/clips/clip-1?sig=1')
  })

  it('names the player, and leaves playing to the user', async () => {
    const { wrapper } = await encoded()
    expect(video(wrapper).attributes('aria-label')).toBe('The preview clip')
    expect(video(wrapper).attributes('autoplay')).toBeUndefined()
    expect(video(wrapper).attributes('controls')).toBeDefined()
  })

  it('shows why the clip link failed', async () => {
    const { wrapper } = await encoded((fake) =>
      fake.on('GET /api/preview/clips/clip-1/link', () =>
        problem(404, 'preview.unknown_clip', 'The clip is not in the cache'),
      ),
    )
    expect(wrapper.text()).toContain('The clip cannot be opened: The clip is not in the cache')
  })

  it('asks for a new link when the player fails, then shows the frame compare', async () => {
    const { wrapper, server } = await encoded()
    await videoError(wrapper, 4)
    expect(server.count('GET /api/preview/clips/clip-1/link')).toBe(2)
    expect(video(wrapper).attributes('src')).toBe('http://server/api/preview/clips/clip-1?sig=2')
    await videoError(wrapper, 4)
    expect(video(wrapper).exists()).toBe(false)
    expect(wrapper.find('[data-field="clip-play-error"]').text()).toContain(
      'this browser cannot play hevc video',
    )
    expect(wrapper.find('[data-field="clip-compare"]').exists()).toBe(true)
  })

  it('names another player error by its message', async () => {
    const { wrapper } = await encoded()
    await videoError(wrapper, 3)
    await videoError(wrapper, 3)
    expect(wrapper.find('[data-field="clip-play-error"]').text()).toContain(
      'the player stopped with an error (Decoder gone)',
    )
  })

  it('asks for a new link again after the clip has played', async () => {
    const { wrapper, server } = await encoded()
    await videoError(wrapper, 4)
    await video(wrapper).trigger('loadeddata')
    await videoError(wrapper, 2)
    expect(server.count('GET /api/preview/clips/clip-1/link')).toBe(3)
    expect(video(wrapper).exists()).toBe(true)
  })

  it('switches between the player and the frame compare', async () => {
    const { wrapper } = await encoded()
    await wrapper.find('[data-action="compare-frames"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-field="clip-compare"]').exists()).toBe(true)
    expect(video(wrapper).exists()).toBe(false)
    await wrapper.find('[data-action="play-clip"]').trigger('click')
    expect(video(wrapper).exists()).toBe(true)
  })

  it('opens the signed clip link in an external player', async () => {
    const open = vi.spyOn(platform, 'openExternal').mockResolvedValue()
    const { wrapper } = await encoded()
    await wrapper.find('[data-action="open-external"]').trigger('click')
    expect(open).toHaveBeenCalledWith('http://server/api/preview/clips/clip-1?sig=1')
  })

  it('says that the clip is out of date after an edit of the job', async () => {
    const { wrapper } = await encoded()
    expect(wrapper.find('[data-field="clip-out-of-date"]').exists()).toBe(false)
    useEditorStore().set('/video/quality', 30)
    await flushPromises()
    expect(wrapper.find('[data-field="clip-out-of-date"]').exists()).toBe(true)
    expect(video(wrapper).exists()).toBe(true)
  })

  it('drops the clip when another file is shown', async () => {
    const { wrapper } = await encoded()
    await useEditorStore().open('other')
    await flushPromises()
    expect(wrapper.find('[data-field="clip-result"]').exists()).toBe(false)
  })

  it('cancels an encode of the last file when another file is shown', async () => {
    const { wrapper, server } = await panel()
    await wrapper.find('[data-action="encode-clip"]').trigger('click')
    await flushPromises()
    await useEditorStore().open('other')
    await flushPromises()
    expect(server.count('POST /api/tasks/t-1/cancel')).toBe(1)
    end({ progress: 100, result: CLIP as never })
    await flushPromises()
    expect(wrapper.find('[data-field="clip-result"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="encode-clip"]').exists()).toBe(true)
  })
})
