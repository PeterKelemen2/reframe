import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mountBase } from '@/components/base/testing'

import CropMagnifier from './CropMagnifier.vue'
import { fakeBitmap, fakeCrop, fakePreview, LETTERBOX, SIZE, strip } from './testing'

const preview = fakePreview()
const crop = fakeCrop()
vi.mock('@/stores/preview', () => ({ usePreviewStore: () => preview }))
vi.mock('@/stores/crop', () => ({ useCropStore: () => crop }))

const frames: FrameRequestCallback[] = []
const drawn: { canvas: HTMLCanvasElement; source: number[] }[] = []
const mounted: VueWrapper[] = []

beforeEach(() => {
  preview.strip = strip()
  preview.index = 2
  preview.current = preview.strip[2]!
  preview.pointer = null
  preview.step.mockReset()
  crop.rect = LETTERBOX
  crop.sourceSize = SIZE
  frames.length = 0
  drawn.length = 0
  vi.stubGlobal('fetch', async () => new Response(new Blob(['png'])))
  vi.stubGlobal('createImageBitmap', async () => fakeBitmap())
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => frames.push(callback))
  vi.stubGlobal('cancelAnimationFrame', () => {})
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (
    this: HTMLCanvasElement,
  ) {
    return recordingContext(this)
  })
})

/** A 2D context that records the source rectangle of each `drawImage` and ignores the rest. */
function recordingContext(canvas: HTMLCanvasElement): never {
  return new Proxy(
    {},
    {
      get: (_, name) =>
        name === 'drawImage'
          ? (_image: unknown, ...source: number[]) => drawn.push({ canvas, source })
          : () => {},
      set: () => true,
    },
  ) as never
}

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function mountMagnifier() {
  const wrapper = mountBase(CropMagnifier)
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

function ranges(wrapper: VueWrapper): Record<string, string> {
  return Object.fromEntries(
    wrapper
      .findAll('[data-edge]')
      .map((figure) => [figure.attributes('data-edge'), figure.find('[data-range]').text()]),
  )
}

async function chooseZoom(wrapper: VueWrapper, label: string): Promise<void> {
  const button = wrapper
    .findAll('[data-field="magnifier-zoom"] button')
    .find((candidate) => candidate.text() === label)
  await button!.trigger('click')
}

describe('the frame navigation', () => {
  it('shows the strip frame and steps through the strip', async () => {
    const wrapper = await mountMagnifier()
    expect(wrapper.find('[data-frame-label]').text()).toBe('Frame 3 / 10')
    await wrapper.find('[data-action="frame-next"]').trigger('click')
    await wrapper.find('[data-action="frame-previous"]').trigger('click')
    expect(preview.step.mock.calls).toEqual([[1], [-1]])
  })

  it('stops at the ends of the strip', async () => {
    preview.index = 0
    const wrapper = await mountMagnifier()
    expect(wrapper.find('[data-action="frame-previous"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-action="frame-next"]').attributes('disabled')).toBeUndefined()
    preview.index = 9
    await flushPromises()
    expect(wrapper.find('[data-action="frame-previous"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-action="frame-next"]').attributes('disabled')).toBeDefined()
  })

  it('names the time of a frame between the strip frames', async () => {
    preview.index = null
    preview.current = { ...preview.strip[0]!, key: 'seek', timestamp: 2.5 }
    const wrapper = await mountMagnifier()
    expect(wrapper.find('[data-frame-label]').text()).toBe('Frame at 0:00:02.500')
  })

  it('opens the check of all frames', async () => {
    Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} })
    vi.stubGlobal(
      'Worker',
      class {
        addEventListener(): void {}
        postMessage(): void {}
        terminate(): void {}
      },
    )
    const wrapper = await mountMagnifier()
    expect(document.querySelector('[data-dialog="crop-check"]')).toBeNull()
    await wrapper.find('[data-action="check-crop"]').trigger('click')
    await flushPromises()
    expect(document.querySelector('[data-dialog="crop-check"]')).not.toBeNull()
  })
})

describe('the edge strips', () => {
  it('show the rows and columns around each crop line at 4×, then at the zoom chosen', async () => {
    const wrapper = await mountMagnifier()
    expect(ranges(wrapper)).toEqual({
      top: 'Rows 10–33',
      bottom: 'Rows 144–167',
      left: 'Columns 0–11',
      right: 'Columns 308–319',
    })
    await chooseZoom(wrapper, '8×')
    expect(ranges(wrapper).top).toBe('Rows 16–27')
    await chooseZoom(wrapper, '2×')
    expect(ranges(wrapper).top).toBe('Rows 0–45')
  })

  it('draw once per animation frame, from the last pointer position', async () => {
    await mountMagnifier()
    frames.splice(0).forEach((callback) => callback(0))
    drawn.length = 0
    preview.pointer = { x: 20, y: 20 }
    await flushPromises()
    preview.pointer = { x: 200, y: 90 }
    await flushPromises()
    expect(frames).toHaveLength(1)
    frames[0]!(16)
    // Four strips, each from its own canvas; the top strip's 96 columns are centred on x = 200.
    expect(new Set(drawn.map((call) => call.canvas)).size).toBe(4)
    expect(drawn).toHaveLength(4)
    expect(drawn[0]!.source.slice(0, 3)).toEqual([152, 10, 96])
  })
})
