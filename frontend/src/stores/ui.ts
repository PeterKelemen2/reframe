import { defineStore } from 'pinia'
import { ref } from 'vue'

import { EDITOR_TABS, type EditorTabId } from '@/components/editor/tabs/registry'

/** Which tab shows the field at a validation path (`video.encoder`, `audio[2].bitrate`). */
const TAB_OF_SECTION: Record<string, EditorTabId> = {
  video: 'video',
  audio: 'audio',
  subtitles: 'subtitles',
  dimensions: 'dimensions',
  filters: 'filters',
  chapters: 'chapters',
  tags: 'tags',
}

export function tabForPath(path: string): EditorTabId {
  const section = /^[a-z_]+/.exec(path)?.[0] ?? ''
  const tab = TAB_OF_SECTION[section] ?? 'summary'
  return EDITOR_TABS.some((built) => built.id === tab) ? tab : 'summary'
}

export interface RevealRequest {
  /** A validation path: `video.encoder`, `audio[2]`, `output.path`. */
  path: string
  /** `performance.now()` of the request: a target that mounts much later ignores it. */
  at: number
}

/** The advanced encoder options panel shows the fields at these paths. */
function inAdvancedPanel(path: string): boolean {
  return (
    path === 'video.advanced' ||
    path.startsWith('video.advanced.') ||
    path === 'video.custom_params'
  )
}

/**
 * UI state that several areas share: the editor's tab, "show me this field", the matrix, the
 * advanced panel.
 */
export const useUiStore = defineStore('ui', () => {
  const activeTab = ref<EditorTabId>('summary')
  const revealed = ref<RevealRequest | null>(null)
  /** The Video tab's advanced options panel is open (for the page, across tabs and jobs). */
  const advancedOpen = ref(false)

  /** Switches to the tab of `path`; the element registered for `path` then shows itself. */
  function reveal(path: string): void {
    activeTab.value = tabForPath(path)
    if (inAdvancedPanel(path)) advancedOpen.value = true
    revealed.value = { path, at: performance.now() }
  }

  /** The target of the request calls this once it has shown itself. */
  function revealDone(request: RevealRequest): void {
    if (revealed.value === request) revealed.value = null
  }

  /** The resolution matrix of the edited group is open. */
  const matrixOpen = ref(false)
  /** The file whose row the matrix scrolls to and focuses when it opens. */
  const matrixFocus = ref<string | null>(null)

  function openMatrix(focus: string | null = null): void {
    matrixFocus.value = focus
    matrixOpen.value = true
  }

  return {
    activeTab,
    revealed,
    reveal,
    revealDone,
    advancedOpen,
    matrixOpen,
    matrixFocus,
    openMatrix,
  }
})
