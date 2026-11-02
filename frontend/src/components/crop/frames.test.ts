import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope, ref } from 'vue'

import { configureClient } from '@/api/client'
import { deferred } from '@/api/testing/fakes'
import type { FrameLink } from '@/api/types'

import { useFrameBitmap } from './frames'
import { fakeBitmap, fakePreview, strip } from './testing'

const preview = fakePreview()
vi.mock('@/stores/preview', () => ({ usePreviewStore: () => preview }))

const fetchMock = vi.fn<(url: URL) => Promise<Response>>()
const decode = vi.fn<(blob: Blob, options: ImageBitmapOptions) => Promise<ImageBitmap>>()
const scopes: EffectScope[] = []

beforeEach(() => {
  configureClient({ baseUrl: 'http://server:8730' })
  fetchMock.mockReset().mockImplementation(async () => new Response(new Blob(['png'])))
  decode.mockReset().mockImplementation(async () => fakeBitmap())
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('createImageBitmap', decode)
  preview.reload.mockReset()
})

afterEach(() => {
  for (const scope of scopes.splice(0)) scope.stop()
  vi.unstubAllGlobals()
  configureClient({ baseUrl: '' })
})

function use(link: () => FrameLink | null) {
  const scope = effectScope()
  scopes.push(scope)
  return { scope, ...scope.run(() => useFrameBitmap(link))! }
}

describe('useFrameBitmap', () => {
  it('fetches the frame from the server and decodes it without colour conversion', async () => {
    const [frame] = strip()
    const { bitmap } = use(() => frame!)
    await flushPromises()
    expect(fetchMock.mock.calls[0]![0].href).toBe(
      'http://server:8730/api/preview/frames/f0.png?exp=1&sig=a',
    )
    expect(decode.mock.calls[0]![1]).toEqual({ colorSpaceConversion: 'none' })
    expect(bitmap.value).not.toBeNull()
  })

  it('shares one bitmap between the users of a frame and closes it after the last one', async () => {
    const [frame] = strip()
    const first = use(() => frame!)
    const second = use(() => frame!)
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(second.bitmap.value).toBe(first.bitmap.value)
    const shown = first.bitmap.value!
    first.scope.stop()
    await flushPromises()
    expect(shown.close).not.toHaveBeenCalled()
    second.scope.stop()
    await flushPromises()
    expect(shown.close).toHaveBeenCalled()
  })

  it('asks for new links once when a link has expired, then says the frame failed', async () => {
    fetchMock.mockImplementation(async () => new Response(null, { status: 401 }))
    const links = ref(strip('old'))
    const { bitmap, failed } = use(() => links.value[0]!)
    await flushPromises()
    expect(preview.reload).toHaveBeenCalledTimes(1)
    expect(failed.value).toBe(false)

    links.value = strip('new')
    await flushPromises()
    expect(fetchMock.mock.calls[1]![0].href).toContain('sig=new')
    expect(preview.reload).toHaveBeenCalledTimes(1)
    expect(failed.value).toBe(true)
    expect(bitmap.value).toBeNull()
  })

  it('shows the frame when the new links work', async () => {
    fetchMock.mockImplementationOnce(async () => new Response(null, { status: 401 }))
    const links = ref(strip('old'))
    const { bitmap, failed } = use(() => links.value[0]!)
    await flushPromises()
    links.value = strip('new')
    await flushPromises()
    expect(bitmap.value).not.toBeNull()
    expect(failed.value).toBe(false)
  })

  it('asks for new links again when links that worked expire later', async () => {
    fetchMock.mockImplementationOnce(async () => new Response(null, { status: 401 }))
    const links = ref(strip('a'))
    const index = ref(0)
    const { bitmap, failed } = use(() => links.value[index.value]!)
    await flushPromises()
    links.value = strip('b')
    await flushPromises()
    expect(bitmap.value).not.toBeNull()

    fetchMock.mockImplementationOnce(async () => new Response(null, { status: 401 }))
    index.value = 1
    await flushPromises()
    expect(preview.reload).toHaveBeenCalledTimes(2)
    expect(failed.value).toBe(false)
  })

  it('keeps the decoded frame when new links to it come', async () => {
    const links = ref(strip('old'))
    const { bitmap } = use(() => links.value[0]!)
    await flushPromises()
    const shown = bitmap.value
    links.value = strip('new')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(bitmap.value).toBe(shown)
  })

  it('shows the last frame asked for when an earlier one comes later', async () => {
    const first = deferred<Response>()
    fetchMock.mockImplementationOnce(() => first.promise)
    const later = fakeBitmap()
    decode.mockImplementationOnce(async () => later)
    const links = strip()
    const shown = ref(links[0]!)
    const { bitmap } = use(() => shown.value)
    shown.value = links[1]!
    await flushPromises()
    expect(bitmap.value).toBe(later)
    first.resolve(new Response(new Blob(['png'])))
    await flushPromises()
    expect(bitmap.value).toBe(later)
  })
})
