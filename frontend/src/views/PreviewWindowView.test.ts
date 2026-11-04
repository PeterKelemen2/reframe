import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it } from 'vitest'
import { effectScope } from 'vue'

import { geometryOf } from '@/components/dimensions/testing'
import { previewServer } from '@/components/preview/testing'
import { shareWithPreviewWindow } from '@/components/shell/previewWindow'
import { mountShell } from '@/components/shell/testing'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'
import { useSourcesStore } from '@/stores/sources'
import { useUiStore } from '@/stores/ui'

import PreviewWindowView from './PreviewWindowView.vue'

const cleanups: (() => void)[] = []

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  document.body.replaceChildren()
  await new Promise((resolve) => setTimeout(resolve, 10))
})

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 10))
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 10))
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 10))
  await flushPromises()
}

/** The main window's page (its own Pinia) with a file open, and the preview window's view. */
async function windows() {
  previewServer().on('POST /api/jobs/geometry', geometryOf())
  const mainPinia = createPinia()
  setActivePinia(mainPinia)
  const scope = effectScope(true)
  scope.run(() => shareWithPreviewWindow())
  cleanups.push(() => scope.stop())
  useSourcesStore().entries = [{ id: 'movie', path: '/m/movie.mkv', source: null }]
  await useEditorStore().open('movie')
  await settle()
  const main = {
    editor: useEditorStore(),
    preview: usePreviewStore(),
    ui: useUiStore(),
  }

  const { wrapper, pinia } = await mountShell(PreviewWindowView, { path: '/preview/movie' })
  cleanups.push(() => (wrapper as VueWrapper).unmount())
  await settle()
  setActivePinia(pinia)
  return { main, wrapper, preview: usePreviewStore() }
}

describe('the preview window', () => {
  it('shows the frame the main window shows, and asks for output frames', async () => {
    const { main, wrapper, preview } = await windows()
    main.preview.select(2)
    await settle()
    const frame = wrapper.find('[data-field="frame"]')
    expect(frame.attributes('src')).toBe(main.preview.current?.url)
    expect(preview.panelOpen).toBe(true)
  })

  it('shows the crop overlay on Dimensions and before/after on Filters', async () => {
    const { main, wrapper } = await windows()
    main.ui.activeTab = 'dimensions'
    main.editor.set('/dimensions/crop', {
      mode: 'manual',
      rect: { top: 20, bottom: 20, left: 0, right: 0 },
    })
    await settle()
    expect(wrapper.find('[data-overlay="crop"]').exists()).toBe(true)

    main.ui.activeTab = 'filters'
    main.preview.viewMode = 'split'
    await settle()
    expect(wrapper.find('[data-overlay="crop"]').exists()).toBe(false)
    expect(wrapper.find('[data-field="stage"]').attributes('data-view')).toBe('split')
  })

  it('steps through the frames with the arrow keys, and the main window follows', async () => {
    const { main, wrapper, preview } = await windows()
    wrapper
      .find('[data-field="thumb"]')
      .element.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    await settle()
    expect(preview.index).toBe(1)
    expect(main.preview.index).toBe(1)
  })
})
