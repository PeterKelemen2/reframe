import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { previewServer } from '@/components/preview/testing'
import { platform } from '@/platform'
import type { DesktopShell } from '@/platform/types'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

import PreviewPanel from './PreviewPanel.vue'
import { PREVIEW_CHANNEL } from './previewWindow'
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

  it('has no preview window to open in the web app', async () => {
    const { wrapper } = await panel()
    expect(wrapper.find('[data-action="detach"]').exists()).toBe(false)
  })

  it('shows the preview large in a dialog in the web app, and the panel says where it is', async () => {
    const { wrapper, preview } = await panel()
    await wrapper.get('[data-action="enlarge"]').trigger('click')
    await flushPromises()
    const dialog = document.querySelector('[data-dialog="preview"]')!
    const thumb = dialog.querySelector('[data-field="thumb"]')!
    expect(wrapper.find('[data-state="enlarged"]').exists()).toBe(true)
    expect(wrapper.find('.preview-panel__content [data-field="thumb"]').exists()).toBe(false)
    expect(preview.panelOpen).toBe(true)
    press(thumb, 'ArrowRight')
    expect(preview.index).toBe(1)
    dialog.querySelector<HTMLElement>('.p-dialog-close-button')!.click()
    await flushPromises()
    expect(wrapper.find('[data-state="enlarged"]').exists()).toBe(false)
    expect(wrapper.find('.preview-panel__content [data-field="thumb"]').exists()).toBe(true)
  })

  it('puts the programme strip directly under the frame, and keeps it while the preview is large', async () => {
    const { wrapper } = await panel()
    const stage = wrapper.get('[data-field="stage"]').element
    expect(stage.nextElementSibling?.getAttribute('data-component')).toBe('programme-strip')
    await wrapper.get('[data-action="enlarge"]').trigger('click')
    await flushPromises()
    const dialog = document.querySelector('[data-dialog="preview"]')!
    expect(dialog.querySelector('[data-component="programme-strip"]')).toBeNull()
    expect(
      wrapper.findAll('.preview-panel__content [data-component="programme-strip"]'),
    ).toHaveLength(1)
  })

  it('has no strip while collapsed: the editor column shows it then', async () => {
    const { wrapper } = await panel(true)
    expect(wrapper.find('[data-component="programme-strip"]').exists()).toBe(false)
  })

  it('draws the picture without smoothing at 100 % and 200 %, and smooths it to fit', async () => {
    const { wrapper, preview } = await panel()
    const pixels = () => wrapper.get('[data-field="stage"]').classes('frame-viewer__stage--pixels')
    expect(pixels()).toBe(false)
    preview.zoom = 1
    await flushPromises()
    expect(pixels()).toBe(true)
    preview.zoom = 2
    await flushPromises()
    expect(pixels()).toBe(true)
  })

  it('closes the large preview when the file is closed', async () => {
    const { wrapper } = await panel()
    await wrapper.get('[data-action="enlarge"]').trigger('click')
    await flushPromises()
    useEditorStore().close()
    await flushPromises()
    expect(wrapper.find('[data-state="enlarged"]').exists()).toBe(false)
    expect(wrapper.get('[data-action="enlarge"]').attributes('disabled')).toBeDefined()
  })
})

/** What the preview window says to the main window. */
function previewWindowSays(kind: 'hello' | 'bye'): Promise<void> {
  const channel = new BroadcastChannel(PREVIEW_CHANNEL)
  // oxlint-disable-next-line unicorn/require-post-message-target-origin -- a channel has no origin argument
  channel.postMessage(JSON.stringify({ kind }))
  channel.close()
  return new Promise((resolve) => setTimeout(resolve, 10))
}

describe('the preview panel in the desktop app', () => {
  let opened: string[]
  let refusal: string | null

  beforeEach(() => {
    opened = []
    refusal = null
    platform.desktop = {
      async openPreviewWindow(sourceId: string) {
        if (refusal !== null) throw refusal
        opened.push(sourceId)
      },
    } as Partial<DesktopShell> as DesktopShell
  })

  afterEach(() => {
    platform.desktop = null
  })

  it('opens the shown file in the preview window', async () => {
    const { wrapper } = await panel()
    await wrapper.find('[data-action="detach"]').trigger('click')
    await flushPromises()
    expect(opened).toEqual(['movie'])
  })

  it('shows where the preview is while it is detached, and asks for no output frames', async () => {
    const { wrapper, preview } = await panel()
    await previewWindowSays('hello')
    await flushPromises()
    expect(wrapper.find('[data-state="detached"]').exists()).toBe(true)
    expect(wrapper.find('[data-field="stage"]').exists()).toBe(false)
    expect(preview.panelOpen).toBe(false)

    await wrapper.find('[data-action="focus-window"]').trigger('click')
    await flushPromises()
    expect(opened).toEqual(['movie'])

    await previewWindowSays('bye')
    await flushPromises()
    expect(wrapper.find('[data-state="detached"]').exists()).toBe(false)
    expect(wrapper.find('[data-field="stage"]').exists()).toBe(true)
    expect(preview.panelOpen).toBe(true)
  })

  it('says why the preview window did not open', async () => {
    refusal = 'Not a source id: ""'
    const { wrapper } = await panel()
    await wrapper.find('[data-action="detach"]').trigger('click')
    await flushPromises()
    expect(useToastStore().items).toEqual([
      expect.objectContaining({ severity: 'error', detail: 'Not a source id: ""' }),
    ])
  })
})
