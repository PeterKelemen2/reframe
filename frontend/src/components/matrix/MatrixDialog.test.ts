import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import type { BatchResolution, SourceEntry } from '@/api/types'
import { createAppI18n } from '@/i18n'
import type { EditorTarget } from '@/stores/editor'
import { useUiStore } from '@/stores/ui'

import MatrixDialog from './MatrixDialog.vue'
import { animeResolution, animeSources, sourceIdOf } from './testing'

// Test doubles of the editor and sources stores: the members their contracts give.
const editor = reactive({
  target: null as EditorTarget | null,
  resolution: null as BatchResolution | null,
  resolving: false,
  matrixError: null as string | null,
  retryMatrix: vi.fn<() => void>(),
  pickTrack: vi.fn<() => void>(),
})
const sources = reactive({ entries: [] as SourceEntry[] })
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
vi.mock('@/stores/sources', () => ({ useSourcesStore: () => sources }))

const mounted: { unmount(): void }[] = []

async function settle(): Promise<void> {
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 20))
  await flushPromises()
}

async function mountDialog() {
  const pinia = createPinia()
  setActivePinia(pinia)
  mounted.push(
    mount(MatrixDialog, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n(), [PrimeVue, { theme: 'none' }]],
        // The dialog binds its Escape key when its enter transition runs.
        stubs: { transition: false },
      },
    }),
  )
  const ui = useUiStore()
  ui.openMatrix()
  await settle()
  return ui
}

function dialog(): HTMLElement | null {
  return document.querySelector('.matrix-dialog')
}

function rows(): number {
  return document.querySelectorAll('[data-row-mark]').length
}

beforeEach(() => {
  editor.target = { kind: 'group', groupId: 'g', overrides: {} } as unknown as EditorTarget
  editor.resolution = animeResolution()
  editor.resolving = false
  editor.matrixError = null
  editor.retryMatrix.mockClear()
  sources.entries = animeSources()
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(() => 720)
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(() => 1200)
  vi.spyOn(HTMLElement.prototype, 'offsetParent', 'get').mockImplementation(() => document.body)
})

afterEach(() => {
  vi.restoreAllMocks()
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

describe('the matrix dialog', () => {
  it("shows the group's name, its file count and the batch's problems on top", async () => {
    editor.resolution = {
      ...animeResolution(),
      issues: [
        { severity: 'error', code: 'batch.name_collision', path: 'output.path', message: 'Two' },
      ],
    }
    await mountDialog()
    expect(dialog()?.querySelector('.p-dialog-title')?.textContent).toBe(
      'Check group “Anime Show S01”',
    )
    expect(dialog()?.querySelector('[data-role="count"]')?.textContent?.trim()).toBe('12 files')
    expect(dialog()?.querySelector('.matrix-dialog__issues')?.textContent).toContain('Two')
    expect(rows()).toBe(12)
  })

  it('shows only the files with problems when asked', async () => {
    await mountDialog()
    dialog()?.querySelector<HTMLInputElement>('#matrix-problems-only')?.click()
    await settle()
    expect(rows()).toBe(2)
  })

  it('closes with its button and with Escape, but Escape in a popover closes the popover only', async () => {
    const ui = await mountDialog()
    const cell = document.querySelector<HTMLElement>(
      `[data-row-mark="${sourceIdOf(5)}"]`,
    ) as HTMLElement
    cell.click()
    await settle()
    const popover = document.querySelector('.matrix-popover')
    popover?.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }),
    )
    await settle()
    expect(ui.matrixOpen).toBe(true)

    cell.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }),
    )
    expect(ui.matrixOpen).toBe(false)

    ui.openMatrix()
    await settle()
    dialog()?.querySelector<HTMLButtonElement>('.p-dialog-close-button')?.click()
    expect(ui.matrixOpen).toBe(false)

    // A click on text leaves the focus nowhere: Escape still closes the matrix.
    ui.openMatrix()
    await settle()
    ;(document.activeElement as HTMLElement | null)?.blur()
    document.body.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }),
    )
    expect(ui.matrixOpen).toBe(false)
  })
})

describe('the matrix dialog for a screen reader and the keyboard', () => {
  it('keeps its live region and changes its text while the group is resolved again', async () => {
    await mountDialog()
    const live = dialog()?.querySelector('[role="status"]')
    expect(live?.textContent?.trim()).toBe('')
    editor.resolving = true
    await settle()
    expect(dialog()?.querySelector('[role="status"]')).toBe(live)
    expect(live?.textContent?.trim()).toBe('Updating…')
  })

  it('names its maximize button by what it does, and focuses the first row first', async () => {
    await mountDialog()
    expect(document.activeElement?.getAttribute('data-row-mark')).toBe(sourceIdOf(1))
    const maximize = dialog()?.querySelector<HTMLButtonElement>('.p-dialog-maximize-button')
    expect(maximize?.getAttribute('aria-label')).toBe('Maximize')
    maximize?.click()
    await settle()
    expect(maximize?.getAttribute('aria-label')).toBe('Restore size')
  })

  it('focuses the problems-only box first while there is no matrix yet', async () => {
    editor.resolution = null
    editor.resolving = true
    await mountDialog()
    expect(document.activeElement?.id).toBe('matrix-problems-only')
  })
})

describe('a failed resolve', () => {
  it('shows the failure with Try again, and the matrix it keeps as out of date', async () => {
    editor.matrixError = 'The server could not be reached.'
    await mountDialog()
    const alert = dialog()?.querySelector('[role="alert"]')
    expect(alert?.textContent).toContain(
      'The matrix could not be updated: The server could not be reached.',
    )
    expect(alert?.textContent).toContain('out of date')
    const shown = dialog()?.querySelector<HTMLElement>('[data-state="outdated"]')
    expect(shown?.hasAttribute('inert')).toBe(true)
    expect(shown?.querySelectorAll('[data-row-mark]')).toHaveLength(12)
    dialog()?.querySelector<HTMLButtonElement>('[data-role="retry"]')?.click()
    expect(editor.retryMatrix).toHaveBeenCalledOnce()

    editor.matrixError = null
    await settle()
    expect(dialog()?.querySelector('[role="alert"]')).toBeNull()
    expect(dialog()?.querySelector('[data-state="outdated"]')).toBeNull()
    expect(dialog()?.querySelector('.matrix-dialog__matrix')?.hasAttribute('inert')).toBe(false)
  })

  it('says that there is no matrix yet when the first resolve failed', async () => {
    editor.resolution = null
    editor.matrixError = 'Boom'
    await mountDialog()
    expect(dialog()?.querySelector('[role="alert"]')?.textContent).toContain(
      'There is no matrix yet.',
    )
    expect(dialog()?.querySelector('[data-role="retry"]')).not.toBeNull()
    expect(rows()).toBe(0)
  })
})
