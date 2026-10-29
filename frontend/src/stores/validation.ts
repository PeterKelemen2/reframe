import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { Severity, ValidationIssue } from '@/api/types'

const SEVERITY_ORDER: Record<Severity, number> = { error: 0, warning: 1, info: 2 }

/** The open job's validation issues (`jobs/validate`), indexed by path for `Field`. */
export const useValidationStore = defineStore('validation', () => {
  const issues = ref<ValidationIssue[]>([])
  /** A validation is waiting for its debounce or its answer. */
  const pending = ref(false)

  const counts = computed<Record<Severity, number>>(() => {
    const result: Record<Severity, number> = { error: 0, warning: 0, info: 0 }
    for (const issue of issues.value) result[issue.severity] += 1
    return result
  })
  const hasErrors = computed(() => counts.value.error > 0)

  /**
   * The issues at `path` (`video.encoder`), most severe first. `nested`: also those below it
   * (`audio[2]` → `audio[2].bitrate`).
   */
  function issuesFor(path: string, options?: { nested?: boolean }): ValidationIssue[] {
    const nested = options?.nested === true
    return issues.value
      .filter(
        (issue) =>
          issue.path === path ||
          (nested && (issue.path.startsWith(`${path}.`) || issue.path.startsWith(`${path}[`))),
      )
      .toSorted((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
  }

  return { issues, pending, counts, hasErrors, issuesFor }
})
