import { computed, type Ref, ref, shallowRef, watch } from 'vue'

import { ApiError } from '@/api/client'
import type { JobState } from '@/api/types'
import { useQueueStore } from '@/stores/queue'

const ENDED = new Set<JobState>(['done', 'failed', 'cancelled', 'interrupted'])

/**
 * A job's whole log, read in chunks from the start, then read on from where it stopped each
 * time the job writes more (`queue.logTicks`) and once more when the job ends.
 */
export function useJobLog(jobId: Ref<string | null>) {
  const queue = useQueueStore()
  /** Every line that ended with a newline. */
  const complete = shallowRef<string[]>([])
  /** The text after the last newline: a chunk can end inside a line. */
  const partial = ref('')
  const loading = ref(false)
  /** The log could not be read (the problem was a toast). */
  const failed = ref(false)
  let next = 0
  let generation = 0
  let reading: Promise<void> | null = null
  let again = false

  const lines = computed<readonly string[]>(() =>
    partial.value === '' ? complete.value : [...complete.value, partial.value],
  )

  function append(chunk: string): void {
    if (chunk === '') return
    const parts = (partial.value + chunk).split(/\r?\n/)
    partial.value = parts.pop() ?? ''
    // A new array: the virtual scroller and `lines` see a change only by reference.
    if (parts.length > 0) complete.value = complete.value.concat(parts)
  }

  async function readAll(id: string, run: number): Promise<void> {
    const chunk = await queue.readLog(id, next)
    if (run !== generation) return
    append(chunk.text)
    next = chunk.next
    if (chunk.more) await readAll(id, run)
  }

  async function drain(id: string, run: number): Promise<void> {
    again = false
    await readAll(id, run)
    if (again && run === generation) await drain(id, run)
  }

  /** Reads from where the last read stopped; a call during a read makes one more read after it. */
  function readOn(): Promise<void> {
    const id = jobId.value
    if (id === null) return Promise.resolve()
    if (reading !== null) {
      again = true
      return reading
    }
    const run = generation
    reading = (async () => {
      try {
        await drain(id, run)
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
        if (run === generation) failed.value = true
      } finally {
        if (run === generation) {
          reading = null
          loading.value = false
        }
      }
    })()
    return reading
  }

  function reset(): void {
    generation += 1
    reading = null
    again = false
    next = 0
    complete.value = []
    partial.value = ''
    failed.value = false
  }

  watch(
    jobId,
    (id) => {
      reset()
      if (id === null) return
      loading.value = true
      void readOn()
    },
    { immediate: true },
  )

  watch(
    () => (jobId.value === null ? undefined : queue.logTicks[jobId.value]),
    (tick, before) => {
      if (tick !== undefined && tick !== before) void readOn()
    },
  )

  watch(
    () => (jobId.value === null ? undefined : queue.byId(jobId.value)?.state),
    (state, before) => {
      if (state !== undefined && before !== undefined && ENDED.has(state) && !ENDED.has(before)) {
        void readOn()
      }
    },
  )

  /** The whole log as it was read. */
  function text(): string {
    return complete.value.map((line) => `${line}\n`).join('') + partial.value
  }

  return { lines, loading, failed, readOn, text }
}
