import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import type { Severity, ValidationIssue } from '@/api/types'

const SEVERITY_ORDER: Record<Severity, number> = { error: 0, warning: 1, info: 2 }

/**
 * The open job's validation issues, indexed by path for `Field`. `useValidation` keeps the
 * server's current; a store that finds issues in its own data adds them with `addLocal`.
 */
export const useValidationStore = defineStore('validation', () => {
  /** The server's issues: `jobs/validate` and the draft's own. */
  const reported = shallowRef<ValidationIssue[]>([])
  /** What finds issues in data the server's job does not hold, by name. */
  const local = shallowRef<Record<string, () => ValidationIssue[]>>({})
  /** Every issue of the open job; setting it replaces the server's issues only. */
  const issues = computed<ValidationIssue[]>({
    get: () => [...reported.value, ...Object.values(local.value).flatMap((find) => find())],
    set: (value) => {
      reported.value = value
    },
  })
  /** A validation is waiting for its debounce or its answer: `issues` may be an older job's. */
  const pending = ref(false)
  /** The last validation failed (no answer): `issues` are an older job's. */
  const failed = ref(false)
  /** +1 for each `revalidate`. */
  const requests = ref(0)
  /** +1 for each `flush`. */
  const flushes = ref(0)
  /** The editor session (`editor.session`) whose job `issues` describe. */
  const session = ref<number | null>(null)

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

  /** Adds the open job's issues that `find` gives (reactive), in place of those of `name`. */
  function addLocal(name: string, find: () => ValidationIssue[]): void {
    local.value = { ...local.value, [name]: find }
  }

  /**
   * Validates the open job again although it did not change: something the job's issues depend
   * on changed on the server.
   */
  function revalidate(): void {
    requests.value += 1
  }

  /**
   * Sends a validation that waits for its debounce at once, or asks again after a failed one:
   * an add to the queue waits for the answer.
   */
  function flush(): void {
    flushes.value += 1
  }

  return {
    issues,
    pending,
    failed,
    requests,
    flushes,
    session,
    counts,
    hasErrors,
    issuesFor,
    addLocal,
    revalidate,
    flush,
  }
})
