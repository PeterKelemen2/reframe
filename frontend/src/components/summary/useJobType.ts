import { onScopeDispose, ref, shallowRef, watch } from 'vue'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, JobTypeInfo } from '@/api/types'
import { latestRequest } from '@/editor/latest'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'

/**
 * `jobs/type` of the editor's job: asked at once for a new job, after the edit debounce
 * otherwise. Only the newest answer is shown.
 */
export function useJobType() {
  const editor = useEditorStore()
  const answer = shallowRef<JobTypeInfo | null>(null)
  /** Why the server could not tell (the problem's title). */
  const error = ref<string | null>(null)
  const pending = ref(false)

  const request = latestRequest<JobTypeInfo>({
    async send(signal) {
      const job = editor.job as JobSettings
      return unwrap(await apiQuiet.POST('/api/jobs/type', { body: { job }, signal }))
    },
    done(value) {
      answer.value = value
      error.value = null
      pending.value = false
    },
    failed(failure) {
      answer.value = null
      error.value = failure instanceof ApiError ? failure.problem.title : String(failure)
      pending.value = false
    },
  })

  let session: number | null = null

  // Almost every part of a job counts, and an edit that changes nothing keeps the frozen job
  // as it is.
  watch(
    () => editor.job,
    (job) => {
      if (job === null) {
        request.cancel()
        answer.value = null
        error.value = null
        pending.value = false
        session = null
        return
      }
      // Another job's type must not stay on screen while this one's is asked for.
      const fresh = session !== editor.session
      session = editor.session
      if (fresh) {
        answer.value = null
        error.value = null
      }
      pending.value = true
      request.schedule(fresh ? 0 : EDIT_DEBOUNCE)
    },
    { immediate: true },
  )

  onScopeDispose(() => request.cancel())

  return { answer, error, pending }
}
