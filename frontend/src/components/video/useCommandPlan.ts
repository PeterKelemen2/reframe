import { onScopeDispose, ref, type Ref, shallowRef, watch } from 'vue'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, Schemas, ValidationIssue } from '@/api/types'
import { latestRequest } from '@/editor/latest'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

type EncodePlan = Schemas['EncodePlan']

/** Why there is no command: the job's errors (`422 jobs.invalid`), or the failure's text. */
export type PlanProblem =
  | { kind: 'invalid'; issues: ValidationIssue[] }
  | { kind: 'failed'; message: string }

export interface CommandPlan {
  plan: Ref<EncodePlan | null>
  problem: Ref<PlanProblem | null>
  /** A newer job is on its way: what shows is for an older one. */
  pending: Ref<boolean>
}

/**
 * `POST /api/jobs/plan` for the open job while `active` is true: at once when it becomes true or
 * a new job opens, 250 ms after the last edit otherwise. The newest request wins.
 */
export function useCommandPlan(active: Ref<boolean>): CommandPlan {
  const editor = useEditorStore()
  const system = useSystemStore()
  const settings = useSettingsStore()
  const plan = shallowRef<EncodePlan | null>(null)
  const problem = shallowRef<PlanProblem | null>(null)
  const pending = ref(false)

  const request = latestRequest<EncodePlan>({
    async send(signal) {
      const body = { job: editor.job as JobSettings }
      return unwrap(await apiQuiet.POST('/api/jobs/plan', { body, signal }))
    },
    done(answer) {
      plan.value = answer
      problem.value = null
      pending.value = false
    },
    failed(error) {
      plan.value = null
      pending.value = false
      if (error instanceof ApiError && error.problem.code === 'jobs.invalid') {
        const issues = (error.problem.issues ?? []).filter((issue) => issue.severity === 'error')
        problem.value = { kind: 'invalid', issues }
      } else {
        const message =
          error instanceof ApiError ? (error.problem.detail ?? error.problem.title) : String(error)
        problem.value = { kind: 'failed', message }
      }
    },
  })

  function stop(): void {
    request.cancel()
    pending.value = false
  }

  // Capabilities, tools and settings change the command (the encoder's device, the tool paths).
  watch(
    () =>
      [
        active.value,
        editor.session,
        editor.job,
        system.capabilities,
        system.info,
        settings.settings,
      ] as const,
    ([on, session, job], previous) => {
      if (!on || job === null) {
        stop()
        if (job === null) {
          plan.value = null
          problem.value = null
        }
        return
      }
      const fresh = previous === undefined || !previous[0] || previous[1] !== session
      if (previous !== undefined && previous[1] !== session) {
        plan.value = null
        problem.value = null
      }
      pending.value = true
      request.schedule(fresh ? 0 : EDIT_DEBOUNCE)
    },
    { immediate: true },
  )
  onScopeDispose(stop)

  return { plan, problem, pending }
}
