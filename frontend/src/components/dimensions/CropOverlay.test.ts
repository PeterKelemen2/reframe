import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { getActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { settle } from '@/api/testing/fakes'
import type { JobSettings } from '@/api/types'
import DimensionsTab from '@/components/editor/tabs/DimensionsTab.vue'
import { mountShell } from '@/components/shell/testing'
import { sampleJob } from '@/editor/testing/samples'
import { useCropStore } from '@/stores/crop'
import { useEditorStore } from '@/stores/editor'
import { useUiStore } from '@/stores/ui'

import CropOverlay from './CropOverlay.vue'
import { setUpCrop } from './testing'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

function manualJob(): JobSettings {
  const job = sampleJob()
  job.dimensions = {
    ...job.dimensions!,
    crop: { mode: 'manual', rect: { top: 22, bottom: 24, left: 0, right: 0 } },
  }
  return job
}

/** The overlay over a 320×180 picture drawn 640×360 at (100, 50). */
async function mountOverlay(job?: JobSettings) {
  const setup = setUpCrop({ job })
  const editor = useEditorStore()
  const crop = useCropStore()
  await editor.open('letterbox')
  await settle()
  setup.detections[0]?.resolve()
  await settle()
  useUiStore().activeTab = 'dimensions'
  const { wrapper } = await mountShell(CropOverlay, { pinia: setup.pinia })
  mounted.push(wrapper)
  await flushPromises()
  const root = wrapper.find('[data-overlay="crop"]')
  if (root.exists()) {
    vi.spyOn(root.element, 'getBoundingClientRect').mockReturnValue({
      left: 100,
      top: 50,
      width: 640,
      height: 360,
    } as DOMRect)
  }
  return { ...setup, wrapper, editor, crop }
}

function handle(wrapper: VueWrapper, edge: string) {
  return wrapper.find(`[data-crop-handle="${edge}"]`)
}

describe('the crop overlay', () => {
  it('tints the removed area and draws the crop in percent of the picture, on Dimensions only', async () => {
    const { wrapper } = await mountOverlay()
    const frame = wrapper.find('.crop-overlay__frame').element as HTMLElement
    expect(frame.style.top).toBe(`${(22 / 180) * 100}%`)
    expect(frame.style.bottom).toBe(`${(24 / 180) * 100}%`)
    expect(frame.style.left).toBe('0%')
    expect(wrapper.findAll('.crop-overlay__removed')).toHaveLength(4)
    // Automatic mode shows the crop but has no handles.
    expect(wrapper.find('[data-crop-handle]').exists()).toBe(false)
    useUiStore().activeTab = 'filters'
    await flushPromises()
    expect(wrapper.find('[data-overlay="crop"]').exists()).toBe(false)
  })

  it('names each handle and its value', async () => {
    const { wrapper } = await mountOverlay(manualJob())
    const top = handle(wrapper, 'top')
    expect(top.attributes()).toMatchObject({
      role: 'slider',
      tabindex: '0',
      'aria-label': 'Top crop edge',
      'aria-valuenow': '22',
      'aria-valuemin': '0',
      // The largest top crop that leaves one chroma row above the bottom crop of 24.
      'aria-valuemax': '154',
    })
    expect(handle(wrapper, 'left').attributes('aria-valuemax')).toBe('318')
    expect(handle(wrapper, 'right').attributes('aria-orientation')).toBe('horizontal')
  })

  it('moves an edge one chroma step per arrow press, more with Shift, as one undo step', async () => {
    const { wrapper, editor } = await mountOverlay(manualJob())
    const top = handle(wrapper, 'top')
    const outside = vi.fn<() => void>()
    wrapper.element.parentElement?.addEventListener('keydown', outside)
    await top.trigger('keydown', { key: 'ArrowDown' })
    await top.trigger('keydown', { key: 'ArrowDown' })
    await top.trigger('keydown', { key: 'ArrowUp' })
    await top.trigger('keydown', { key: 'ArrowDown', shiftKey: true })
    expect(editor.get('/dimensions/crop/rect')).toMatchObject({ top: 22 + 2 + 16, bottom: 24 })
    await handle(wrapper, 'bottom').trigger('keydown', { key: 'ArrowUp' })
    expect(editor.get('/dimensions/crop/rect')).toMatchObject({ bottom: 26 })
    await handle(wrapper, 'right').trigger('keydown', { key: 'ArrowRight' })
    expect(outside).not.toHaveBeenCalled()
    editor.undo()
    editor.undo()
    expect(editor.get('/dimensions/crop/rect')).toMatchObject({ top: 22, bottom: 24 })
  })

  it('moves an edge to either end of its range with Home and End', async () => {
    const { wrapper, editor } = await mountOverlay(manualJob())
    const top = handle(wrapper, 'top')
    const outside = vi.fn<() => void>()
    wrapper.element.parentElement?.addEventListener('keydown', outside)
    await top.trigger('keydown', { key: 'End' })
    expect(editor.get('/dimensions/crop/rect')).toMatchObject({ top: 154, bottom: 24 })
    expect(top.attributes('aria-valuenow')).toBe('154')
    await top.trigger('keydown', { key: 'Home' })
    expect(editor.get('/dimensions/crop/rect')).toMatchObject({ top: 0, bottom: 24 })
    expect(outside).not.toHaveBeenCalled()
  })

  it('moves an edge eight steps a page, the vertical ones the way the key points', async () => {
    const { wrapper, editor } = await mountOverlay(manualJob())
    const rect = () => editor.get('/dimensions/crop/rect')
    await handle(wrapper, 'top').trigger('keydown', { key: 'PageDown' })
    expect(rect()).toMatchObject({ top: 22 + 16 })
    await handle(wrapper, 'top').trigger('keydown', { key: 'PageUp' })
    expect(rect()).toMatchObject({ top: 22 })
    await handle(wrapper, 'bottom').trigger('keydown', { key: 'PageUp' })
    expect(rect()).toMatchObject({ bottom: 24 + 16 })
    await handle(wrapper, 'right').trigger('keydown', { key: 'PageUp' })
    await handle(wrapper, 'left').trigger('keydown', { key: 'PageUp' })
    expect(rect()).toMatchObject({ left: 16, right: 16 })
    await handle(wrapper, 'left').trigger('keydown', { key: 'PageDown' })
    expect(rect()).toMatchObject({ left: 0 })
  })

  it('shows nothing while the video is copied', async () => {
    const job = manualJob()
    job.video = { ...job.video!, passthrough: true }
    const { wrapper } = await mountOverlay(job)
    expect(wrapper.find('[data-overlay="crop"]').exists()).toBe(false)
  })

  it('gives the focus to the crop mode when an undo takes the handles away', async () => {
    const job = manualJob()
    job.dimensions!.crop = { mode: 'conservative', rect: null }
    const { wrapper, editor, crop } = await mountOverlay(job)
    const { wrapper: tab } = await mountShell(DimensionsTab, { pinia: getActivePinia() })
    mounted.push(tab)
    await crop.setMode('manual')
    await flushPromises()
    ;(handle(wrapper, 'top').element as HTMLElement).focus()
    editor.undo()
    await flushPromises()
    expect(document.activeElement?.closest('[data-control="crop-mode"]')).not.toBeNull()
    expect(document.activeElement?.textContent).toBe('Conservative')
  })

  it('writes no note for a value the user did not type', async () => {
    const { wrapper, crop } = await mountOverlay(manualJob())
    await handle(wrapper, 'left').trigger('keydown', { key: 'ArrowLeft' })
    expect(crop.snapNote).toBeNull()
    const left = handle(wrapper, 'left')
    left.element.setPointerCapture = () => {}
    const send = (type: string, clientX = 0) =>
      left.element.dispatchEvent(new MouseEvent(type, { button: 0, clientX, clientY: 200 }))
    send('pointerdown')
    send('pointermove', 20)
    send('pointerup')
    await flushPromises()
    expect(crop.snapNote).toBeNull()
  })

  it('drags an edge to the pointer, one undo step per drag', async () => {
    const { wrapper, editor } = await mountOverlay(manualJob())
    // In a group the edits of a drag are on their way to the server when it ends.
    const ended = vi.spyOn(editor, 'endCoalescing')
    const left = handle(wrapper, 'left')
    left.element.setPointerCapture = () => {}
    // jsdom has no PointerEvent; a MouseEvent of the same type carries what the overlay reads.
    const send = (type: string, clientX = 0) =>
      left.element.dispatchEvent(new MouseEvent(type, { button: 0, clientX, clientY: 200 }))
    const drag = async (xs: number[]) => {
      send('pointerdown')
      for (const clientX of xs) send('pointermove', clientX)
      send('pointerup')
      await flushPromises()
    }
    // 100 + 41 × 2: source x 41, snapped down to 40.
    await drag([120, 160, 182])
    expect(editor.get('/dimensions/crop/rect')).toMatchObject({ left: 40 })
    expect(ended).toHaveBeenCalledTimes(1)
    await drag([200])
    expect(editor.get('/dimensions/crop/rect')).toMatchObject({ left: 50 })
    editor.undo()
    expect(editor.get('/dimensions/crop/rect')).toMatchObject({ left: 40 })
    editor.undo()
    expect(editor.get('/dimensions/crop/rect')).toMatchObject({ left: 0, top: 22 })
  })
})
