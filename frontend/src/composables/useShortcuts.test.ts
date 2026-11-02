import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, reactive, ref } from 'vue'

import type { SystemInfo } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import { useShortcuts } from './useShortcuts'

const editor = reactive({
  canUndo: true,
  canRedo: true,
  undo: vi.fn<() => void>(),
  redo: vi.fn<() => void>(),
})
const sources = reactive({ pick: vi.fn<() => Promise<void>>() })
const canAdd = ref(true)
const addCurrent = vi.fn<() => Promise<void>>()
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
vi.mock('@/stores/sources', () => ({ useSourcesStore: () => sources }))
vi.mock('./useQueueActions', () => ({ useQueueActions: () => ({ canAdd, addCurrent }) }))

const Host = defineComponent({
  setup() {
    useShortcuts()
    return () => null
  },
})

const mounted: { unmount(): void }[] = []

async function mountAt(path = '/', phase: 'ready' | 'login' = 'ready') {
  const result = await mountShell(Host, {
    path,
    pinia: createPinia(),
    setup: () => {
      useSystemStore().phase = phase
    },
  })
  mounted.push(result.wrapper)
  return result
}

function press(
  key: string,
  options: { shift?: boolean; code?: string; repeat?: boolean; target?: Element } = {},
): KeyboardEvent {
  const event = new KeyboardEvent('keydown', {
    key,
    code: options.code ?? '',
    ctrlKey: true,
    shiftKey: options.shift ?? false,
    repeat: options.repeat ?? false,
    bubbles: true,
    cancelable: true,
  })
  ;(options.target ?? document.body).dispatchEvent(event)
  return event
}

function element(html: string): HTMLElement {
  const host = document.createElement('div')
  host.innerHTML = html
  document.body.append(host)
  return host.querySelector('[data-target]') as HTMLElement
}

beforeEach(() => {
  editor.canUndo = true
  editor.canRedo = true
  editor.undo.mockReset()
  editor.redo.mockReset()
  sources.pick.mockReset().mockResolvedValue()
  canAdd.value = true
  addCurrent.mockReset().mockResolvedValue()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

describe('Ctrl+O', () => {
  it('opens files instead of the browser dialog', async () => {
    await mountAt()
    const event = press('o')
    expect(event.defaultPrevented).toBe(true)
    expect(sources.pick).toHaveBeenCalledTimes(1)
  })

  it('goes to the workspace first from another view', async () => {
    const { router } = await mountAt('/queue')
    let routeAtPick: unknown
    sources.pick.mockImplementation(async () => {
      routeAtPick = router.currentRoute.value.name
    })
    press('o')
    await vi.waitFor(() => expect(sources.pick).toHaveBeenCalled())
    expect(routeAtPick).toBe('workspace')
  })

  it('does nothing while FFmpeg cannot be used, on the login screen, or held down', async () => {
    await mountAt()
    press('o', { repeat: true })
    useSystemStore().info = {
      tools: {
        ffmpeg: { name: 'ffmpeg', status: 'missing' },
        ffprobe: { name: 'ffprobe', status: 'found' },
      },
    } as SystemInfo
    press('o')
    useSystemStore().info = null
    useSystemStore().phase = 'login'
    press('o')
    expect(sources.pick).not.toHaveBeenCalled()
  })
})

describe('Ctrl+Enter', () => {
  it('adds the job once per press, also when it could not be added before the press', async () => {
    await mountAt()
    expect(press('Enter').defaultPrevented).toBe(true)
    press('Enter', { repeat: true })
    // The value typed into the focused field may be what fixes the job: the add decides.
    canAdd.value = false
    press('Enter', { target: element('<input data-target type="text">') })
    expect(addCurrent).toHaveBeenCalledTimes(2)
  })

  it('does nothing outside the workspace', async () => {
    await mountAt('/settings')
    press('Enter')
    expect(addCurrent).not.toHaveBeenCalled()
  })
})

describe('Ctrl+1…8', () => {
  it('selects the tab with that shortcut', async () => {
    await mountAt()
    const ui = useUiStore()
    press('4', { code: 'Digit4' })
    expect(ui.activeTab).toBe('video')
    // The browser must not switch its own tab.
    expect(press('2', { code: 'Digit2' }).defaultPrevented).toBe(true)
    expect(ui.activeTab).toBe('dimensions')
    press('5', { code: 'Numpad5' })
    expect(ui.activeTab).toBe('audio')
    // A layout where the key prints another character: the physical key counts.
    press('&', { code: 'Digit1' })
    expect(ui.activeTab).toBe('summary')
    press('6', { code: 'Digit6', shift: true })
    expect(ui.activeTab).toBe('summary')
  })

  it("gives the focus to the selected tab's button, not to the page", async () => {
    await mountAt()
    const field = element(
      '<div role="tablist"><button role="tab" data-tab="summary"></button><button role="tab" data-tab="video"></button></div><input data-target type="checkbox">',
    )
    field.focus()
    press('4', { code: 'Digit4', target: field })
    expect(document.activeElement).toBe(document.querySelector('[data-tab="video"]'))
    // Shortcut 2 has no built tab, so it takes no focus either.
    press('2', { code: 'Digit2' })
    expect(document.activeElement).toBe(document.querySelector('[data-tab="video"]'))
  })
})

describe('undo and redo', () => {
  it('Ctrl+Z undoes, Ctrl+Shift+Z and Ctrl+Y redo', async () => {
    await mountAt()
    expect(press('z').defaultPrevented).toBe(true)
    press('Z', { shift: true })
    press('y')
    expect(editor.undo).toHaveBeenCalledTimes(1)
    expect(editor.redo).toHaveBeenCalledTimes(2)
  })

  it('leaves them to a text field, a textarea and a contenteditable while it has the focus', async () => {
    await mountAt()
    for (const html of [
      '<input data-target type="text">',
      '<input data-target type="number">',
      '<textarea data-target></textarea>',
      '<div contenteditable="true"><span data-target></span></div>',
    ]) {
      const target = element(html)
      expect.soft(press('z', { target }).defaultPrevented).toBe(false)
      press('Z', { shift: true, target })
    }
    expect(editor.undo).not.toHaveBeenCalled()
    expect(editor.redo).not.toHaveBeenCalled()
  })

  it('undoes the editor from a number field, which keeps no typing of its own to undo', async () => {
    await mountAt()
    const target = element('<span class="p-inputnumber"><input data-target type="text"></span>')
    expect(press('z', { target }).defaultPrevented).toBe(true)
    press('Z', { shift: true, target })
    expect(editor.undo).toHaveBeenCalledTimes(1)
    expect(editor.redo).toHaveBeenCalledTimes(1)
  })

  it('undoes the editor from a check box, which has no typing to undo', async () => {
    await mountAt()
    press('z', { target: element('<input data-target type="checkbox">') })
    expect(editor.undo).toHaveBeenCalledTimes(1)
  })

  it('does nothing when there is nothing to undo or redo', async () => {
    await mountAt()
    editor.canUndo = false
    editor.canRedo = false
    press('z')
    press('y')
    expect(editor.undo).not.toHaveBeenCalled()
    expect(editor.redo).not.toHaveBeenCalled()
  })

  it('does not undo the editor from another view', async () => {
    await mountAt('/presets')
    press('z')
    expect(editor.undo).not.toHaveBeenCalled()
  })

  it('does not undo the editor while the first-run screen replaces it', async () => {
    await mountAt()
    useSystemStore().info = {
      tools: {
        ffmpeg: { name: 'ffmpeg', status: 'missing' },
        ffprobe: { name: 'ffprobe', status: 'found' },
      },
    } as SystemInfo
    press('z')
    press('Enter')
    expect(editor.undo).not.toHaveBeenCalled()
    expect(addCurrent).not.toHaveBeenCalled()
  })

  it('leaves the keys to a modal dialog that has the focus', async () => {
    await mountAt()
    const target = element(
      '<div role="dialog" aria-modal="true"><button data-target></button></div>',
    )
    press('z', { target })
    press('o', { target })
    expect(editor.undo).not.toHaveBeenCalled()
    expect(sources.pick).not.toHaveBeenCalled()
  })

  it('acts on nothing behind an open modal dialog after a click on its text left the focus on the page', async () => {
    await mountAt()
    const ui = useUiStore()
    const before = ui.activeTab
    element('<div role="dialog" aria-modal="true"><p data-target>Text</p></div>')
    press('z')
    press('Enter')
    press('5', { code: 'Digit5' })
    press('o')
    expect(editor.undo).not.toHaveBeenCalled()
    expect(addCurrent).not.toHaveBeenCalled()
    expect(ui.activeTab).toBe(before)
    expect(sources.pick).not.toHaveBeenCalled()
  })

  it('undoes and redoes in the matrix and its popovers, where picks and fixes are made', async () => {
    await mountAt()
    const ui = useUiStore()
    const before = ui.activeTab
    element('<div role="dialog" aria-modal="true" class="matrix-dialog"><p data-target>M</p></div>')
    press('z')
    press('Z', { shift: true })
    press('Enter')
    press('5', { code: 'Digit5' })
    press('o')
    expect(editor.undo).toHaveBeenCalledTimes(1)
    expect(editor.redo).toHaveBeenCalledTimes(1)
    expect(addCurrent).not.toHaveBeenCalled()
    expect(ui.activeTab).toBe(before)
    expect(sources.pick).not.toHaveBeenCalled()

    const field = element(
      '<div role="dialog" aria-modal="true" class="matrix-popover"><input data-target type="text"></div>',
    )
    press('z')
    expect(editor.undo).toHaveBeenCalledTimes(2)
    press('z', { target: field })
    expect(editor.undo).toHaveBeenCalledTimes(2)
  })

  it('leaves the keys to a dialog opened over the matrix', async () => {
    await mountAt()
    element('<div role="dialog" aria-modal="true" class="matrix-dialog"></div>')
    element('<div role="dialog" aria-modal="true"><p data-target>Queue?</p></div>')
    press('z')
    expect(editor.undo).not.toHaveBeenCalled()
  })

  it('works again while the last modal closes: a picked preset leaves its list fading out', async () => {
    await mountAt()
    element(
      '<div data-target role="dialog" aria-modal="true" class="p-popover p-anchored-overlay-leave-active"></div>',
    )
    press('5', { code: 'Digit5' })
    expect(useUiStore().activeTab).toBe('audio')
  })
})

it('stops listening when the shell unmounts', async () => {
  const { wrapper } = await mountAt()
  mounted.splice(0)
  wrapper.unmount()
  press('z')
  press('o')
  expect(editor.undo).not.toHaveBeenCalled()
  expect(sources.pick).not.toHaveBeenCalled()
})
