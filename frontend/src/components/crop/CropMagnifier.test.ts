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
/** The content width the fake `ResizeObserver` reports for every element it observes. */
let room = 386
const resizes: (() => void)[] = []
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
  room = 386
  resizes.length = 0
  vi.stubGlobal(
    'ResizeObserver',
    class {
      constructor(private readonly callback: ResizeObserverCallback) {}
      observe(target: Element): void {
        const report = () =>
          this.callback(
            [{ target, contentBoxSize: [{ inlineSize: room, blockSize: 0 }] } as never],
            this as never,
          )
        resizes.push(report)
        queueMicrotask(report)
      }
      unobserve(): void {}
      disconnect(): void {}
    },
  )
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

  it('says at the ends of the strip that there is no frame further, and keeps the focus', async () => {
    preview.index = 8
    const wrapper = await mountMagnifier()
    const next = wrapper.find<HTMLButtonElement>('[data-action="frame-next"]')
    const previous = wrapper.find<HTMLButtonElement>('[data-action="frame-previous"]')
    next.element.focus()
    preview.index = 9
    await flushPromises()
    expect(next.attributes('aria-disabled')).toBe('true')
    expect(previous.attributes('aria-disabled')).toBeUndefined()
    // A disabled button drops the focus to the page.
    expect(next.element.disabled).toBe(false)
    expect(document.activeElement).toBe(next.element)
    preview.index = 0
    await flushPromises()
    expect(previous.attributes('aria-disabled')).toBe('true')
    expect(previous.element.disabled).toBe(false)
    expect(next.attributes('aria-disabled')).toBeUndefined()
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

  it('fit the width they have: the top and bottom strips as long as fits, in whole pixels', async () => {
    room = 264
    const wrapper = await mountMagnifier()
    frames.splice(0).forEach((callback) => callback(0))
    const canvas = (edge: string) => wrapper.find<HTMLCanvasElement>(`[data-edge="${edge}"] canvas`)
    // 264 less the canvas border, in whole source pixels at 8×.
    expect(canvas('top').element.style.width).toBe('256px')
    expect(canvas('bottom').element.style.width).toBe('256px')
    expect(canvas('left').element.style.height).toBe('384px')
    const top = drawn.find((call) => call.canvas === canvas('top').element)!
    expect(top.source.slice(0, 3)).toEqual([128, 10, 64])

    // A wider column: longer strips, drawn again.
    room = 520
    drawn.length = 0
    resizes.forEach((report) => report())
    await flushPromises()
    frames.splice(0).forEach((callback) => callback(16))
    expect(canvas('top').element.style.width).toBe('512px')
    const wider = drawn.find((call) => call.canvas === canvas('top').element)!
    expect(wider.source.slice(0, 3)).toEqual([96, 10, 128])
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
    // Four strips, each from its own canvas; the top strip's 384 / 4 columns are centred on x = 200.
    expect(new Set(drawn.map((call) => call.canvas)).size).toBe(4)
    expect(drawn).toHaveLength(4)
    expect(drawn[0]!.source.slice(0, 3)).toEqual([152, 10, 96])
  })
})
