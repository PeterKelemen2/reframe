import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { problem } from '@/api/testing/fakes'
import { frameLink, previewServer } from '@/components/preview/testing'
import { mountShell } from '@/components/shell/testing'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'

import FrameViewer from './FrameViewer.vue'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function viewer(options: { open?: boolean; server?: ReturnType<typeof previewServer> } = {}) {
  const server = options.server ?? previewServer()
  const { wrapper } = await mountShell(FrameViewer)
  mounted.push(wrapper)
  const preview = usePreviewStore()
  preview.panelOpen = true
  if (options.open !== false) {
    await useEditorStore().open('movie')
    await flushPromises()
  }
  return { wrapper, preview, server }
}

describe('the frame viewer', () => {
  it('asks for a file while none is shown', async () => {
    const { wrapper } = await viewer({ open: false })
    expect(wrapper.find('[data-state="empty"]').text()).toBe('Open a file to see its frames.')
    expect(wrapper.find('[data-field="seek"]').exists()).toBe(false)
  })

  it('shows a failed strip with its reason, and asks again on Try again', async () => {
    const server = previewServer()
    server.on('POST /api/preview/frames', () => problem(422, 'preview.failed', 'No video'))
    const { wrapper } = await viewer({ server })
    expect(wrapper.find('[data-state="error"]').text()).toContain(
      'The frames could not be made: No video',
    )
    previewServer()
    await wrapper.find('[data-action="retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-field="thumb"]')).toHaveLength(10)
  })

  it('shows the strip, marks the current frame and shows a clicked one', async () => {
    const { wrapper } = await viewer()
    const thumbs = wrapper.findAll('[data-field="thumb"]')
    expect(thumbs).toHaveLength(10)
    expect(thumbs[0]!.attributes('aria-current')).toBe('true')
    await thumbs[6]!.trigger('click')
    expect(wrapper.find('[data-field="frame"]').attributes('src')).toBe(
      'http://server/frames/movie-2600-source.png',
    )
    expect(thumbs[6]!.attributes('aria-current')).toBe('true')
    expect(thumbs[0]!.attributes('aria-current')).toBeUndefined()
    expect(wrapper.find('[data-field="position"]').text()).toBe('Frame 7 of 10 · 2.6 s')
  })

  it('seeks to a typed time', async () => {
    const { wrapper, server } = await viewer()
    const input = wrapper.find('[data-field="seek"] input')
    await input.setValue('2.5')
    await input.trigger('blur')
    await wrapper.find('[data-field="seek"]').trigger('submit')
    await flushPromises()
    expect(server.requests.at(-1)?.body).toEqual({ source_id: 'movie', timestamps: [2.5] })
    expect(wrapper.find('[data-field="frame"]').attributes('src')).toBe(
      'http://server/frames/movie-2500-source.png',
    )
    expect(wrapper.find('[data-field="position"]').text()).toBe('2.5 s')
  })

  it('sizes the picture box for each zoom', async () => {
    const { wrapper, preview } = await viewer()
    const box = () => wrapper.find('.frame-viewer__picture').attributes('style')
    expect(box()).toContain('width: min(100%, 106.66')
    preview.zoom = 1
    await flushPromises()
    expect(box()).toContain('width: 320px')
    preview.zoom = 2
    await flushPromises()
    expect(box()).toContain('width: 640px')
  })

  it('sets the pointer in source pixels over the overlay layer, and clears it on leave', async () => {
    const { wrapper, preview } = await viewer()
    const layer = wrapper.find('[data-layer="overlay"]')
    layer.element.getBoundingClientRect = () =>
      ({ left: 100, top: 50, width: 160, height: 90 }) as DOMRect
    // jsdom has no PointerEvent; the handler reads only what a MouseEvent has.
    layer.element.dispatchEvent(new MouseEvent('pointermove', { clientX: 140, clientY: 95 }))
    expect(preview.pointer).toEqual({ x: 80, y: 90 })
    await layer.trigger('pointerleave')
    expect(preview.pointer).toBeNull()
  })

  it('shows the output frame, the split and side by side in their view modes', async () => {
    const { wrapper, preview } = await viewer()
    preview.viewMode = 'output'
    await flushPromises()
    expect(wrapper.find('[data-field="output"]').attributes('src')).toBe(
      'http://server/frames/movie-200-output.png',
    )
    expect(wrapper.find('[data-layer="overlay"]').exists()).toBe(false)
    preview.viewMode = 'split'
    await flushPromises()
    expect(wrapper.find('.split-compare').attributes('data-layout')).toBe('split')
    preview.viewMode = 'side'
    await flushPromises()
    expect(wrapper.find('.split-compare').attributes('data-layout')).toBe('side')
    expect(wrapper.find('.split-compare').attributes('style')).toContain('width: 100%')
    preview.zoom = 1
    await flushPromises()
    expect(wrapper.find('.split-compare').attributes('style')).toContain('width: 1280px')
  })

  it('shows a failed render with its reason', async () => {
    const server = previewServer()
    server.on('POST /api/preview/render', () => problem(422, 'preview.failed', 'Bad filter'))
    const { wrapper, preview } = await viewer({ server })
    preview.viewMode = 'split'
    await flushPromises()
    expect(wrapper.find('[data-state="render-failed"]').text()).toBe(
      'The output frame could not be made: Bad filter',
    )
  })

  it('shows that the output frame is on its way', async () => {
    const server = previewServer()
    server.on('POST /api/preview/render', () => new Promise(() => {}))
    const { wrapper, preview } = await viewer({ server })
    preview.viewMode = 'output'
    await flushPromises()
    expect(wrapper.find('[data-state="rendering"]').exists()).toBe(true)
  })

  it('asks again for a frame whose image did not load, then shows that it failed', async () => {
    const { wrapper, server } = await viewer()
    await wrapper.find('[data-field="frame"]').trigger('error')
    await flushPromises()
    expect(server.count('POST /api/preview/frames')).toBe(2)
    expect(wrapper.find('[data-state="image-failed"]').exists()).toBe(false)
    await wrapper.find('[data-field="frame"]').trigger('error')
    expect(wrapper.find('[data-state="image-failed"]').text()).toBe(
      'The frame could not be loaded.',
    )
  })

  it("adds the render's own notes once in a view with the output frame", async () => {
    const hdr = 'The source is HDR10: the frames are tone mapped to SDR.'
    const output = 'The output stays HDR: the output frames are tone mapped too.'
    const server = previewServer()
    server.on('POST /api/preview/frames', { frames: [frameLink(0.2)], notes: [hdr] })
    server.on('POST /api/preview/render', {
      frames: [frameLink(0.2), frameLink(0.2, 'output')],
      notes: [hdr, output],
    })
    const { wrapper, preview } = await viewer({ server })
    const notes = () => wrapper.findAll('[data-field="notes"] li').map((item) => item.text())
    preview.viewMode = 'output'
    await flushPromises()
    expect(notes()).toEqual([hdr, output])
    preview.viewMode = 'source'
    await flushPromises()
    expect(notes()).toEqual([hdr])
  })

  it("shows the strip's notes", async () => {
    const server = previewServer()
    server.on('POST /api/preview/frames', {
      frames: [],
      notes: ['The source is HDR10: the frames are tone mapped to SDR.'],
    })
    const { wrapper } = await viewer({ server })
    expect(wrapper.find('[data-field="notes"]').text()).toBe(
      'The source is HDR10: the frames are tone mapped to SDR.',
    )
  })
})
