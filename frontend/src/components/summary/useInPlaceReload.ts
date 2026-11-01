import { watch } from 'vue'

import { ApiError } from '@/api/client'
import type { JobState, QueueJob } from '@/api/types'
import { useQueueStore } from '@/stores/queue'
import { useSourcesStore } from '@/stores/sources'
import { TaskLostError } from '@/stores/tasks'

const ENDED = new Set<JobState>(['done', 'failed', 'cancelled', 'interrupted'])

function editedInPlace(job: QueueJob): boolean {
  return job.settings.output?.edit_in_place === true && Boolean(job.started_at)
}

/**
 * Reads an open source again when a job that edited it in place ends, so that its track tables
 * show what the file now holds. Call it once, where it runs whatever view is shown.
 */
export function useInPlaceReload(): void {
  const queue = useQueueStore()
  const sources = useSourcesStore()
  /** The state each job had at the last look; `null` until the queue's first read. */
  let states: Map<string, JobState> | null = null

  watch(
    () => [queue.loaded, queue.jobs] as const,
    ([loaded, jobs]) => {
      if (!loaded) return
      const before = states
      states = new Map(jobs.map((job) => [job.id, job.state]))
      // The jobs that ended before this window saw the queue are not this window's news.
      if (before === null) return
      const paths = new Set<string>()
      for (const job of jobs) {
        const last = before.get(job.id)
        const ended = ENDED.has(job.state) && (last === undefined || !ENDED.has(last))
        if (ended && editedInPlace(job)) paths.add(job.settings.source.path)
      }
      for (const entry of sources.entries) {
        if (paths.has(entry.path)) void sources.reload(entry.id).catch(shown)
      }
    },
    { immediate: true },
  )
}

/** The sources store has shown the reason as a toast. */
function shown(error: unknown): void {
  if (!(error instanceof ApiError) && !(error instanceof TaskLostError)) throw error
}
