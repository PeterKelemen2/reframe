import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { QueueProcessingEvent, ReframeEvent } from '@/api/types'

export interface ActivityEntry {
  /** When the event arrived. */
  at: Date
  event: ReframeEvent | QueueProcessingEvent
}

/** The global activity log: every event of this session, newest last, bounded. */
export const useActivityStore = defineStore('activity', () => {
  const entries = ref<ActivityEntry[]>([])

  /** The event dispatcher calls it for every event. */
  function record(event: ReframeEvent | QueueProcessingEvent): void {
    entries.value.push({ at: new Date(), event })
  }

  function clear(): void {
    entries.value = []
  }

  return { entries, record, clear }
})
