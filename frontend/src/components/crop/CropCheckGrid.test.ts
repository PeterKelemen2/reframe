import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mountBase } from '@/components/base/testing'

import type { CheckAnswer, CheckRequest } from './cropCheck'
import CropCheckGrid from './CropCheckGrid.vue'
import { edgesText } from '@/components/dimensions/testing'

import { detection, fakeCrop, fakePreview, LETTERBOX, PILLARBOX, SIZE, strip } from './testing'

const preview = fakePreview()
const crop = fakeCrop()
vi.mock('@/stores/preview', () => ({ usePreviewStore: () => preview }))
vi.mock('@/stores/crop', () => ({ useCropStore: () => crop }))

class FakeWorker {
  static started: FakeWorker[] = []
  readonly posted: CheckRequest[] = []
  terminated = false
  private listener: ((event: MessageEvent<CheckAnswer>) => void) | null = null

  constructor(readonly url: URL) {
    FakeWorker.started.push(this)
  }

  addEventListener(_type: string, listener: (event: MessageEvent<CheckAnswer>) => void): void {
    this.listener = listener
  }

  postMessage(request: CheckRequest): void {
    this.posted.push(request)
  }

  terminate(): void {
    this.terminated = true
  }

  answer(key: string, lost: boolean): void {
    this.listener?.({ data: { key, variances: [lost ? 6000 : 0.4], lost } } as MessageEvent)
  }

  fail(key: string, error: string): void {
    this.listener?.({ data: { key, error } } as MessageEvent)
  }
}

const fetchMock = vi.fn<(url: string) => Promise<Response>>()
const revoked: string[] = []
const mounted: VueWrapper[] = []

beforeEach(() => {
  preview.strip = strip()
  preview.select.mockReset()
  preview.imageFailed.mockReset().mockReturnValue(true)
  crop.rect = LETTERBOX
  crop.sourceSize = SIZE
  crop.detection = detection()
  crop.detecting = false
  FakeWorker.started = []
  revoked.length = 0
  fetchMock.mockReset().mockImplementation(async () => new Response(new Blob(['png'])))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('Worker', FakeWorker)
  let made = 0
  Object.assign(URL, {
    createObjectURL: () => `blob:frame-${made++}`,
    revokeObjectURL: (url: string) => revoked.push(url),
  })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.unstubAllGlobals()
})

async function mountGrid() {
  const wrapper = mountBase(CropCheckGrid, {
    props: {
      visible: true,
      'onUpdate:visible': (shown: boolean) => wrapper.setProps({ visible: shown }),
    },
  })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

function frame(index: number): HTMLElement {
  return document.querySelector<HTMLElement>(`[data-frame="${index}"]`)!
}

/** The accessible name of a button: its `aria-label`, else its text outside `aria-hidden`. */
function nameOf(element: Element): string {
  const label = element.getAttribute('aria-label')
  if (label !== null) return label
  const parts: string[] = []
  const walk = (node: Node): void => {
    if (node instanceof Element && node.getAttribute('aria-hidden') === 'true') return
    if (node.nodeType === Node.TEXT_NODE) parts.push(node.textContent ?? '')
    node.childNodes.forEach(walk)
  }
  walk(element)
  return parts.join(' ').replaceAll(/\s+/g, ' ').trim()
}

function worker(): FakeWorker {
  return FakeWorker.started.at(-1)!
}

describe('the crop check', () => {
  it('asks a worker about every frame, with the bands the crop removes', async () => {
    await mountGrid()
    expect(FakeWorker.started).toHaveLength(1)
    expect(worker().url.pathname).toMatch(/cropCheck\.worker\.ts$/)
    expect(worker().posted.map((request) => request.key)).toEqual(preview.strip.map((f) => f.key))
    expect(worker().posted[0]!.bands).toEqual([
      { x: 0, y: 0, width: 320, height: 22 },
      { x: 0, y: 156, width: 320, height: 24 },
    ])
    expect(frame(0).querySelector('img')!.getAttribute('src')).toBe('blob:frame-0')
  })

  it('puts the warning badge on the frames that lose content, and only there', async () => {
    await mountGrid()
    preview.strip.forEach((link, i) => worker().answer(link.key, i >= 5))
    await flushPromises()
    const badged = preview.strip
      .map((_, i) => i)
      .filter((i) => frame(i).querySelector('[data-badge="lost"]') !== null)
    expect(badged).toEqual([5, 6, 7, 8, 9])
    expect(frame(5).textContent).toContain('Removes picture')
    expect(document.querySelector('[data-check-summary]')!.textContent).toContain(
      'The crop removes picture content on 5 of 10 frames.',
    )
  })

  it('names on each frame button its time, its detected bars and the badge', async () => {
    await mountGrid()
    preview.strip.forEach((link, i) => worker().answer(link.key, i >= 5))
    await flushPromises()
    const lost = nameOf(frame(5))
    expect(lost).toContain('0:00:02.200')
    expect(lost).toContain('Bars T 0 · B 0 · L 40 · R 40')
    expect(lost).toContain('Removes picture')
    const kept = nameOf(frame(0))
    expect(kept).toContain('0:00:00.200')
    expect(kept).toContain('Bars T 22 · B 24 · L 0 · R 0')
    expect(kept).not.toContain('Removes picture')
  })

  it('says a frame could not be checked, with the reason, and stops saying it is checking', async () => {
    await mountGrid()
    worker().answer('f0', false)
    worker().fail('f1', 'InvalidStateError: The source image could not be decoded.')
    await flushPromises()
    expect(document.querySelector('[role="alert"]')!.textContent).toContain(
      'A frame could not be checked: InvalidStateError: The source image could not be decoded.',
    )
    expect(document.body.textContent).not.toContain('Checking')
  })

  it('says it is checking until every frame has its answer', async () => {
    await mountGrid()
    worker().answer('f0', false)
    await flushPromises()
    expect(document.querySelector('[data-check-summary]')!.textContent).toContain('Checking')
  })

  it('shows on each frame the bars detected at its time', async () => {
    crop.detection = { ...detection(), samples: detection().samples.toReversed().slice(0, 9) }
    await mountGrid()
    expect(frame(1).textContent).toContain(edgesText('Bars T 22 · B 24 · L 0 · R 0'))
    expect(frame(1).querySelectorAll('[data-bar]')).toHaveLength(2)
    expect(frame(6).textContent).toContain(edgesText('Bars T 0 · B 0 · L 40 · R 40'))
    expect(frame(0).textContent).toContain('No detection result')
    expect(frame(0).querySelectorAll('[data-bar]')).toHaveLength(0)
  })

  it('says the bars are being detected while detection runs', async () => {
    crop.detection = null
    crop.detecting = true
    await mountGrid()
    expect(frame(0).textContent).toContain('Detecting the bars…')
  })

  it('shows a frame in the panel when it is chosen, and closes', async () => {
    const wrapper = await mountGrid()
    frame(7).click()
    await flushPromises()
    expect(preview.select).toHaveBeenCalledWith(7)
    expect(wrapper.props('visible')).toBe(false)
  })

  it('stops the worker and frees the images when it closes', async () => {
    const wrapper = await mountGrid()
    await wrapper.setProps({ visible: false })
    expect(worker().terminated).toBe(true)
    expect(revoked).toHaveLength(10)
  })

  it('checks again for another crop and ignores the answers of the last check', async () => {
    await mountGrid()
    const last = worker()
    crop.rect = PILLARBOX
    await flushPromises()
    expect(FakeWorker.started).toHaveLength(2)
    expect(last.terminated).toBe(true)
    expect(worker().posted[0]!.bands).toHaveLength(2)
    expect(worker().posted[0]!.bands[0]).toMatchObject({ x: 0, width: 40 })
    last.answer('f0', true)
    await flushPromises()
    expect(frame(0).querySelector('[data-badge="lost"]')).toBeNull()
  })

  it('hands expired links to the preview store and checks the new strip', async () => {
    fetchMock.mockImplementationOnce(async () => new Response(null, { status: 401 }))
    await mountGrid()
    expect(preview.imageFailed).toHaveBeenCalledWith(preview.strip[0])
    expect(document.querySelector('[role="alert"]')).toBeNull()
    preview.strip = strip('new')
    await flushPromises()
    expect(fetchMock.mock.calls.at(-1)![0]).toContain('sig=new')
    expect(worker().posted).toHaveLength(10)
  })

  it('says the frames failed when the preview store will not ask again', async () => {
    fetchMock.mockImplementation(async () => new Response(null, { status: 401 }))
    preview.imageFailed.mockReturnValueOnce(false)
    await mountGrid()
    expect(document.querySelector('[role="alert"]')!.textContent).toContain(
      'The frames could not be loaded.',
    )
    expect(FakeWorker.started).toHaveLength(0)
  })
})
