import { useEventListener } from '@vueuse/core'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { EDITOR_TABS } from '@/components/editor/tabs/registry'
import { isTextField } from '@/editor/focus'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import { useQueueActions } from './useQueueActions'

// Not the key's target: after a click on a dialog's text the focus, and the target, is `<body>`.
// A closing one (its Vue leave transition) is still in the page, but does not hold the keys.
function topModal(): Element | undefined {
  return [...document.querySelectorAll('[aria-modal="true"]:not([class*="-leave-active"])')].at(-1)
}

function inNumberField(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest('.p-inputnumber') !== null
}

/**
 * Picks, fixes and name corrections are made in the matrix and its popovers, and range changes
 * in the range popover: undo them there.
 */
function undoesInModal(modal: Element): boolean {
  return modal.matches('.matrix-dialog, .matrix-popover, .range-popover')
}

/** `Digit1` … `Digit8` (and the keypad's), whatever the keyboard layout prints on the key. */
function digitOf(code: string): number | null {
  const match = /^(?:Digit|Numpad)([1-8])$/.exec(code)
  return match ? Number(match[1]) : null
}

function ignoreShown(promise: Promise<void>): void {
  promise.catch((error: unknown) => {
    // The API client has shown it as a toast.
    if (!(error instanceof ApiError)) throw error
  })
}

/**
 * The app's keyboard shortcuts. Called once, by the app shell; removed when it unmounts.
 */
export function useShortcuts(): void {
  const route = useRoute()
  const router = useRouter()
  const system = useSystemStore()
  const sources = useSourcesStore()
  const editor = useEditorStore()
  const ui = useUiStore()
  const actions = useQueueActions()

  function open(): void {
    if (system.ffmpegProblem !== null) return
    ignoreShown(
      (async () => {
        if (route.name !== 'workspace') await router.push({ name: 'workspace' })
        await sources.pick()
      })(),
    )
  }

  function onKeydown(event: KeyboardEvent): void {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.defaultPrevented) return
    // The detached preview window shows the preview alone: no editor, no workspace to go to.
    if (system.phase !== 'ready' || route.meta.bare) return
    const key = event.key.toLowerCase()
    const undo = key === 'z' && !event.shiftKey
    const redo = (key === 'z' && event.shiftKey) || (key === 'y' && !event.shiftKey)
    const modal = topModal()
    if (modal !== undefined && !((undo || redo) && undoesInModal(modal))) return

    if (key === 'o' && !event.shiftKey) {
      event.preventDefault()
      if (!event.repeat) open()
      return
    }
    // The rest act on the editor, which only the workspace shows.
    if (route.name !== 'workspace' || system.ffmpegProblem !== null) return

    const digit = event.shiftKey ? null : digitOf(event.code)
    if (digit !== null) {
      event.preventDefault()
      const tab = EDITOR_TABS.find((candidate) => candidate.shortcut === digit)
      if (tab) {
        ui.activeTab = tab.id
        // The old tab's panel goes, and the focus in it with it: the new tab's button takes it.
        document
          .querySelector<HTMLElement>(`[role="tab"][data-tab="${tab.id}"]`)
          ?.focus({ focusVisible: true })
      }
      return
    }
    if (key === 'enter' && !event.shiftKey) {
      event.preventDefault()
      // Even when the job cannot be added as it was: the focused field may hold what fixes it.
      if (!event.repeat) void actions.addCurrent()
      return
    }
    if (!undo && !redo) return
    // Left to the browser: it undoes the typing. A number field rewrites its text on every key,
    // which leaves the browser nothing to undo, so the editor undoes there.
    if (isTextField(event.target) && !inNumberField(event.target)) return
    event.preventDefault()
    if (undo && editor.canUndo) editor.undo()
    if (redo && editor.canRedo) editor.redo()
  }

  useEventListener(window, 'keydown', onKeydown)
}
