import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, Schemas } from '@/api/types'
import { latestRequest } from '@/editor/latest'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'

type JobGeometry = Schemas['JobGeometry']

/**
 * What `jobs/geometry` reads of a job: the source, the dimensions, the passthrough switch and
 * the filters (a deinterlaced source is cropped on the frame's grid).
 */
function geometryKey(job: JobSettings): string {
  return JSON.stringify([job.source, job.dimensions, job.video?.passthrough, job.filters])
}

/**
 * `jobs/geometry` of the editor's job: at once for a new job, 250 ms after the last edit that
 * changes it, and only the newest answer is shown.
 */
export function useGeometry() {
  const editor = useEditorStore()
  const answer = shallowRef<JobGeometry | null>(null)
  /** Why the server could not compute it (the problem's title). */
  const error = ref<string | null>(null)
  const pending = ref(false)

  const request = latestRequest<JobGeometry>({
    async send(signal) {
      const job = editor.job as JobSettings
      return unwrap(await apiQuiet.POST('/api/jobs/geometry', { body: { job }, signal }))
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

  const key = computed(() => (editor.job === null ? null : geometryKey(editor.job)))
  let session: number | null = null

  watch(
    key,
    (current) => {
      if (current === null) {
        request.cancel()
        answer.value = null
        error.value = null
        pending.value = false
        session = null
        return
      }
      // Another job's picture must not stay on screen while this one's is asked for.
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
