import type { ComputedRef } from 'vue'

import { notBuilt } from '@/notBuilt'

export interface QueueGroup {
  /** A group is being resolved or queued. */
  busy: ComputedRef<boolean>
  /**
   * *Add group to queue*: edits the group `groupId` when it is not the edited one, resolves it,
   * and queues one job per file in episode order; when files have errors, asks first (queue the
   * valid files, open the matrix, or cancel).
   */
  queueGroup(groupId: string): Promise<void>
}

export function useQueueGroup(): QueueGroup {
  return notBuilt('useQueueGroup')
}
