import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { previewServer } from '@/components/preview/testing'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'
import { useUiStore } from '@/stores/ui'

import PreviewPanel from './PreviewPanel.vue'
import { mountShell } from './testing'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function panel(collapsed = false) {
  previewServer()
  const { wrapper } = await mountShell(PreviewPanel, { props: { collapsed } })
  mounted.push(wrapper)
  await useEditorStore().open('movie')
  await flushPromises()
  return { wrapper, preview: usePreviewStore(), ui: useUiStore() }
}

function press(target: Element, key: string, options: KeyboardEventInit = {}): void {
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, ...options }))
}

describe('the preview panel', () => {
  it('shows the source on Dimensions, the split on Filters and the chosen view elsewhere', async () => {
    const { preview, ui } = await panel()
    preview.viewMode = 'side'
    await flushPromises()
    ui.activeTab = 'dimensions'
    await flushPromises()
    expect(preview.viewMode).toBe('source')
    ui.activeTab = 'filters'
    await flushPromises()
    expect(preview.viewMode).toBe('split')
    ui.activeTab = 'audio'
    await flushPromises()
    expect(preview.viewMode).toBe('side')
  })

  it('asks for output frames only while it is open', async () => {
    const { wrapper, preview } = await panel(true)
    expect(preview.panelOpen).toBe(false)
    await wrapper.setProps({ collapsed: false })
    expect(preview.panelOpen).toBe(true)
    wrapper.unmount()
    mounted.pop()
    expect(preview.panelOpen).toBe(false)
  })

  it('moves through the frames with the arrow keys while the focus is in it', async () => {
    const { wrapper, preview } = await panel()
    const thumb = wrapper.find('[data-field="thumb"]').element
    press(thumb, 'ArrowRight')
    press(thumb, 'ArrowRight')
    expect(preview.index).toBe(2)
    press(thumb, 'ArrowLeft')
    expect(preview.index).toBe(1)
    press(thumb, 'ArrowRight', { shiftKey: true })
    expect(preview.index).toBe(1)
  })

  it('leaves the arrow keys to a focused stage whose picture is wider than it', async () => {
    const { wrapper, preview } = await panel()
    preview.zoom = 2
    await flushPromises()
    const stage = wrapper.find('[data-field="stage"]').element
    Object.defineProperty(stage, 'clientWidth', { value: 300 })
    Object.defineProperty(stage, 'scrollWidth', { configurable: true, value: 640 })
    const event = new KeyboardEvent('keydown', {
      key: 'ArrowRight',
      bubbles: true,
      cancelable: true,
    })
    stage.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
    expect(preview.index).toBe(0)

    Object.defineProperty(stage, 'scrollWidth', { value: 300 })
    press(stage, 'ArrowRight')
    expect(preview.index).toBe(1)
  })

  it('leaves the arrow keys to a text field, a slider and a crop handle', async () => {
    const { wrapper, preview } = await panel()
    press(wrapper.find('[data-field="seek"] input').element, 'ArrowRight')
    const handle = document.createElement('button')
    handle.dataset.cropHandle = 'top'
    const inner = handle.appendChild(document.createElement('span'))
    wrapper.find('[data-layer="overlay"]').element.append(handle)
    press(inner, 'ArrowRight')
    preview.viewMode = 'split'
    await flushPromises()
    press(wrapper.find('input[type="range"]').element, 'ArrowRight')
    expect(preview.index).toBe(0)
  })
})
