import { computed, onScopeDispose, ref, type Ref, shallowRef, watch } from 'vue'

import { ApiError } from '@/api/client'
import type { JobSettings, OutputChapters } from '@/api/types'
import { latestRequest } from '@/editor/latest'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'

import { outputChapters } from './requests'

export interface OutputChaptersState {
  chapters: Ref<OutputChapters | null>
  /** Why the server gave no list; `null` when it did. */
  failure: Ref<string | null>
  /** A newer job is on its way: what shows is for an older one. */
  pending: Ref<boolean>
}

/**
 * The output's chapters for the open job: at once for a new job, 250 ms after an edit of what
 * the list depends on. The newest request wins.
 */
export function useOutputChapters(): OutputChaptersState {
  const editor = useEditorStore()
  const chapters = shallowRef<OutputChapters | null>(null)
  const failure = ref<string | null>(null)
  const pending = ref(false)

  const request = latestRequest<OutputChapters>({
    send: (signal) => outputChapters(editor.job as JobSettings, signal),
    done(answer) {
      chapters.value = answer
      failure.value = null
      pending.value = false
    },
    failed(error) {
      pending.value = false
      failure.value =
        error instanceof ApiError ? (error.problem.detail ?? error.problem.title) : String(error)
    },
  })

  // Only what the output's chapters depend on: a tag or encoder edit asks nothing.
  const key = computed(() => {
    const job = editor.job
    if (job === null) return null
    return JSON.stringify([job.source, job.range, job.chapters, job.output?.container])
  })

  watch(
    () => [editor.session, key.value] as const,
    ([session, current], previous) => {
      const fresh = previous === undefined || previous[0] !== session
      if (fresh) {
        chapters.value = null
        failure.value = null
      }
      if (current === null) {
        request.cancel()
        pending.value = false
        return
      }
      pending.value = true
      request.schedule(fresh ? 0 : EDIT_DEBOUNCE)
    },
    { immediate: true },
  )
  onScopeDispose(() => request.cancel())

  return { chapters, failure, pending }
}
