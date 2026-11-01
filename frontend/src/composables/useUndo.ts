import { type ComputedRef, computed } from 'vue'

import { useEditorStore } from '@/stores/editor'

export interface Undo {
  canUndo: ComputedRef<boolean>
  canRedo: ComputedRef<boolean>
  undo(): void
  redo(): void
}

/** The editor's undo history, for buttons and menus. */
export function useUndo(): Undo {
  const editor = useEditorStore()
  return {
    canUndo: computed(() => editor.canUndo),
    canRedo: computed(() => editor.canRedo),
    undo: () => editor.undo(),
    redo: () => editor.redo(),
  }
}
