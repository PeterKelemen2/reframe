import { type ComputedRef, computed } from 'vue'

import { notBuilt } from '@/notBuilt'

export interface QueueActions {
  /** The editor's job has no error, and nothing is in the way of adding it. */
  canAdd: ComputedRef<boolean>
  /** Adds the editor's job (`Ctrl+Enter`, *Add to queue*). */
  addCurrent(): Promise<void>
  /** Drafts every open source with the editor's preset and adds those without errors. */
  addAll(): Promise<void>
  /** Starts the queue. */
  start(): Promise<void>
}

/** The status bar's queue actions; the shortcut uses `addCurrent` too. */
export function useQueueActions(): QueueActions {
  return {
    canAdd: computed(() => false),
    addCurrent: () => notBuilt('queueActions.addCurrent'),
    addAll: () => notBuilt('queueActions.addAll'),
    start: () => notBuilt('queueActions.start'),
  }
}
