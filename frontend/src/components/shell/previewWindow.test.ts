import { flushPromises } from '@vue/test-utils'
import { createPinia, type Pinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type EffectScope, effectScope } from 'vue'

import { previewServer } from '@/components/preview/testing'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'
import { useSourcesStore } from '@/stores/sources'
import { useUiStore } from '@/stores/ui'

import { followMainWindow, PREVIEW_CHANNEL, shareWithPreviewWindow } from './previewWindow'

/** One page: its own Pinia, as each window has. */
interface Page {
  pinia: Pinia
  scope: EffectScope
  use<T>(store: () => T): T
}

const pages: Page[] = []

function page(start: () => unknown): Page & { result: unknown } {
  const pinia = createPinia()
  setActivePinia(pinia)
  const scope = effectScope(true)
  const result = scope.run(start)
  const made = {
    pinia,
    scope,
    result,
    use<T>(store: () => T): T {
      setActivePinia(pinia)
      return store()
    },
  }
  pages.push(made)
  return made
}

/** The channel's messages are delivered on a later turn of the event loop. */
async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 10))
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 10))
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 10))
  await flushPromises()
}

async function mainWithFile() {
  const main = page(() => shareWithPreviewWindow())
  const detached = (main.result as ReturnType<typeof shareWithPreviewWindow>).detached
  const sources = main.use(useSourcesStore)
  sources.entries = [{ id: 'movie', path: '/m/movie.mkv', source: null }]
  await main.use(useEditorStore).open('movie')
  await settle()
  return { main, detached }
}

beforeEach(() => {
  previewServer()
})

afterEach(async () => {
  for (const each of pages.splice(0)) each.scope.stop()
  await settle()
  vi.restoreAllMocks()
})

describe('the detached preview window', () => {
  it('shows the main window’s file, job, tab, view, zoom and frame when it opens', async () => {
    const { main, detached } = await mainWithFile()
    main.use(useUiStore).activeTab = 'video'
    main.use(usePreviewStore).viewMode = 'side'
    main.use(usePreviewStore).zoom = 2
    main.use(usePreviewStore).select(3)
    await settle()
    expect(detached.value).toBe(false)

    const preview = page(() => followMainWindow())
    await settle()

    expect(detached.value).toBe(true)
    expect(preview.use(useEditorStore).target?.sourceId).toBe('movie')
    expect(preview.use(useEditorStore).job).toEqual(main.use(useEditorStore).job)
    expect(preview.use(useSourcesStore).entries.map((entry) => entry.id)).toEqual(['movie'])
    expect(preview.use(useUiStore).activeTab).toBe('video')
    expect(preview.use(usePreviewStore).viewMode).toBe('side')
    expect(preview.use(usePreviewStore).zoom).toBe(2)
    expect(preview.use(usePreviewStore).index).toBe(3)
  })

  it('follows a tab change and a crop change in the main window', async () => {
    const { main } = await mainWithFile()
    const preview = page(() => followMainWindow())
    await settle()

    main.use(useUiStore).activeTab = 'dimensions'
    main.use(usePreviewStore).viewMode = 'source'
    const rect = { top: 20, bottom: 20, left: 0, right: 0 }
    main.use(useEditorStore).set('/dimensions/crop', { mode: 'manual', rect })
    await settle()

    expect(preview.use(useUiStore).activeTab).toBe('dimensions')
    expect(preview.use(usePreviewStore).viewMode).toBe('source')
    expect(preview.use(useEditorStore).job?.dimensions?.crop).toEqual({ mode: 'manual', rect })
  })

  it('follows another file in the main window, at the frame the main window shows', async () => {
    const { main } = await mainWithFile()
    const preview = page(() => followMainWindow())
    await settle()
    main.use(usePreviewStore).select(5)
    await settle()

    main.use(useSourcesStore).entries = [
      ...main.use(useSourcesStore).entries,
      { id: 'other', path: '/m/other.mkv', source: null },
    ]
    await main.use(useEditorStore).open('other')
    await settle()

    expect(preview.use(useEditorStore).target?.sourceId).toBe('other')
    // The main window's strip of the new file starts at its first frame.
    expect(main.use(usePreviewStore).index).toBe(0)
    expect(preview.use(usePreviewStore).index).toBe(0)
  })

  it('sends a crop handle’s edits to the main window, one undo step per drag', async () => {
    const { main } = await mainWithFile()
    const preview = page(() => followMainWindow())
    await settle()
    const before = main.use(useEditorStore).job?.dimensions?.crop

    const editor = preview.use(useEditorStore)
    for (const top of [10, 12, 14]) {
      editor.set(
        '/dimensions/crop',
        { mode: 'manual', rect: { top, bottom: 0, left: 0, right: 0 } },
        { coalesce: 'crop.drag.1' },
      )
    }
    editor.endCoalescing()
    await settle()

    const mainEditor = main.use(useEditorStore)
    expect(mainEditor.job?.dimensions?.crop?.rect?.top).toBe(14)
    mainEditor.undo()
    expect(mainEditor.job?.dimensions?.crop).toEqual(before)
    await settle()
    expect(preview.use(useEditorStore).job?.dimensions?.crop).toEqual(before)
  })

  it('sends the user’s frame and view to the main window', async () => {
    const { main } = await mainWithFile()
    const preview = page(() => followMainWindow())
    await settle()

    preview.use(usePreviewStore).select(7)
    preview.use(usePreviewStore).viewMode = 'split'
    await settle()

    expect(main.use(usePreviewStore).index).toBe(7)
    expect(main.use(usePreviewStore).viewMode).toBe('split')
  })

  it('tells the main window when it closes', async () => {
    const { detached } = await mainWithFile()
    const preview = page(() => followMainWindow())
    await settle()
    expect(detached.value).toBe(true)

    preview.scope.stop()
    await settle()

    expect(detached.value).toBe(false)
  })

  it('is found again by a main page that loads after it', async () => {
    const first = await mainWithFile()
    page(() => followMainWindow())
    await settle()
    first.main.scope.stop()

    const { detached } = await mainWithFile()

    expect(detached.value).toBe(true)
  })

  it('sends nothing while no preview window is open', async () => {
    const heard: string[] = []
    const listener = new BroadcastChannel(PREVIEW_CHANNEL)
    listener.addEventListener('message', (event: MessageEvent<string>) => heard.push(event.data))
    const { main } = await mainWithFile()
    main.use(useUiStore).activeTab = 'filters'
    await settle()
    listener.close()

    expect(heard.map((data) => (JSON.parse(data) as { kind: string }).kind)).toEqual(['ask'])
  })
})
