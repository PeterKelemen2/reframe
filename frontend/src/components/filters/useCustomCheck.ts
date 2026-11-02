import { onScopeDispose, shallowRef, watch } from 'vue'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, ValidationIssue } from '@/api/types'
import { latestRequest } from '@/editor/latest'
import { useEditorStore } from '@/stores/editor'

/** Milliseconds from the last key press to the one-frame test: it runs FFmpeg. */
export const CHECK_DELAY = 500

export interface CustomCheck {
  /** The filter whose text was checked. */
  id: string
  text: string
  /** FFmpeg's refusals; `null` while the test runs. */
  errors: ValidationIssue[] | null
}

/**
 * Checks the free filter text that was typed last with `POST /api/jobs/dry-run`, once the typing
 * stops. Only the newest text's answer counts.
 */
export function useCustomCheck() {
  const editor = useEditorStore()
  const check = shallowRef<CustomCheck | null>(null)

  const request = latestRequest<ValidationIssue[]>({
    async send(signal) {
      const body = { job: editor.job as JobSettings }
      try {
        return unwrap(await apiQuiet.POST('/api/jobs/dry-run', { body, signal }))
      } catch (error) {
        // Web mode refuses a filter outside its allow-list before FFmpeg runs.
        if (!(error instanceof ApiError) || error.problem.code !== 'filter.not_allowed') throw error
        const message = error.problem.detail ?? error.problem.title
        return [{ severity: 'error', code: error.problem.code, path: '', message }]
      }
    },
    done(issues) {
      const current = check.value
      if (current === null) return
      check.value = { ...current, errors: issues.filter((issue) => issue.severity === 'error') }
    },
    failed() {
      check.value = null
    },
  })

  function changed(id: string, text: string): void {
    if (text.trim() === '') {
      request.cancel()
      check.value = null
      return
    }
    check.value = { id, text, errors: null }
    request.schedule(CHECK_DELAY)
  }

  /** The check of filter `id`'s text as it is now; `null` when that text was not checked. */
  function of(id: string, text: string): CustomCheck | null {
    const current = check.value
    return current !== null && current.id === id && current.text === text ? current : null
  }

  watch(
    () => editor.session,
    () => {
      request.cancel()
      check.value = null
    },
  )
  onScopeDispose(() => request.cancel())

  return { changed, of }
}
