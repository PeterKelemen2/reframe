import type { Component } from 'vue'

/** Every editor tab, in its order; `Ctrl+N` selects the N-th. */
export const EDITOR_TAB_ORDER = [
  'summary',
  'dimensions',
  'filters',
  'video',
  'audio',
  'subtitles',
  'chapters',
  'tags',
] as const

export type EditorTabId = (typeof EDITOR_TAB_ORDER)[number]

export interface EditorTab {
  id: EditorTabId
  /** vue-i18n key of the tab's label. */
  labelKey: string
  /** The N of its `Ctrl+N` shortcut: its place in `EDITOR_TAB_ORDER`, counted from 1. */
  shortcut: number
  component: () => Promise<Component>
}

function tab(id: EditorTabId, component: () => Promise<Component>): EditorTab {
  return {
    id,
    labelKey: `app.tabs.${id}`,
    shortcut: EDITOR_TAB_ORDER.indexOf(id) + 1,
    component,
  }
}

/**
 * The built tabs. A tab that is not in this list is not shown, and its shortcut does nothing.
 */
export const EDITOR_TABS: readonly EditorTab[] = [
  tab('summary', () => import('./SummaryTab.vue')),
  tab('video', () => import('./VideoTab.vue')),
  tab('audio', () => import('./AudioTab.vue')),
  tab('subtitles', () => import('./SubtitlesTab.vue')),
  tab('chapters', () => import('./ChaptersTab.vue')),
  tab('tags', () => import('./TagsTab.vue')),
]
