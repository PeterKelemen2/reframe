import { onScopeDispose, shallowRef, watch } from 'vue'

import { apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, ValidationIssue } from '@/api/types'
import { CHECK_DELAY } from '@/components/filters/useCustomCheck'
import { latestRequest } from '@/editor/latest'
import { useEditorStore } from '@/stores/editor'

/** The one-frame test of the custom parameters as they are now. */
export type ParamsCheck =
  | { state: 'checking' }
  | { state: 'done'; issues: ValidationIssue[] }
  | { state: 'failed'; reason: string }

// A failed test encode is reported at the encoder: with custom parameters typed, they are the
// likely cause, so the field shows it too.
const SHOWN_PATHS = new Set(['video.custom_params', 'video.encoder'])

/**
 * Checks the job's custom parameters with `POST /api/jobs/dry-run` once they stop changing, and
 * again for another job. Only the newest text's answer counts; `null` while there is no text.
 */
export function useParamsCheck() {
  const editor = useEditorStore()
  const check = shallowRef<ParamsCheck | null>(null)

  const request = latestRequest<ValidationIssue[]>({
    async send(signal) {
      const body = { job: editor.job as JobSettings }
      return unwrap(await apiQuiet.POST('/api/jobs/dry-run', { body, signal }))
    },
    done(issues) {
      check.value = { state: 'done', issues: issues.filter((issue) => SHOWN_PATHS.has(issue.path)) }
    },
    failed(error) {
      check.value = { state: 'failed', reason: (error as Error).message }
    },
  })

  watch(
    [() => editor.session, () => editor.job?.video?.custom_params ?? ''],
    ([, text]) => {
      if (text.trim() === '') {
        request.cancel()
        check.value = null
        return
      }
      check.value = { state: 'checking' }
      request.schedule(CHECK_DELAY)
    },
    { immediate: true },
  )
  onScopeDispose(() => request.cancel())

  return check
}
