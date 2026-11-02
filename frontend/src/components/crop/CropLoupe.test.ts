import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mountBase } from '@/components/base/testing'
import { useUiStore } from '@/stores/ui'

import CropLoupe from './CropLoupe.vue'
import { fakeBitmap, fakeCrop, fakePreview, LETTERBOX, SIZE, strip } from './testing'

const preview = fakePreview()
const crop = fakeCrop()
vi.mock('@/stores/preview', () => ({ usePreviewStore: () => preview }))
vi.mock('@/stores/crop', () => ({ useCropStore: () => crop }))

const fetchMock = vi.fn<(url: URL) => Promise<Response>>()
const mounted: VueWrapper[] = []

beforeEach(() => {
  preview.strip = strip()
  preview.current = preview.strip[0]!
  preview.pointer = { x: 80, y: 45 }
  crop.rect = LETTERBOX
  crop.sourceSize = SIZE
  crop.editable = true
  fetchMock.mockReset().mockImplementation(async () => new Response(new Blob(['png'])))
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('createImageBitmap', async () => fakeBitmap())
  vi.stubGlobal('requestAnimationFrame', () => 1)
  vi.stubGlobal('cancelAnimationFrame', () => {})
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  vi.unstubAllGlobals()
})

async function mountLoupe(tab: 'dimensions' | 'video' = 'dimensions') {
  const wrapper = mountBase(CropLoupe)
  mounted.push(wrapper)
  useUiStore().activeTab = tab
  await flushPromises()
  return wrapper
}

function loupe(wrapper: VueWrapper) {
  return wrapper.find('[data-crop-loupe]')
}

describe('the loupe', () => {
  it('follows the pointer, placed in percent of the source picture', async () => {
    const wrapper = await mountLoupe()
    expect(loupe(wrapper).attributes('style')).toContain('left: 25%; top: 25%')
    preview.pointer = { x: 240, y: 90 }
    await flushPromises()
    expect(loupe(wrapper).attributes('style')).toContain('left: 75%; top: 50%')
  })

  it('hides when the pointer leaves the picture', async () => {
    const wrapper = await mountLoupe()
    preview.pointer = null
    await flushPromises()
    expect(loupe(wrapper).exists()).toBe(false)
  })

  it('shows only in manual crop', async () => {
    crop.editable = false
    const wrapper = await mountLoupe()
    expect(loupe(wrapper).exists()).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows only on the Dimensions tab, and loads no frame on the others', async () => {
    const wrapper = await mountLoupe('video')
    expect(loupe(wrapper).exists()).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
