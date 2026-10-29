import { computed, type ComputedRef, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { ValidationIssue } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

/** The value at `pointer` (RFC 6901) in `document`; `undefined` when a member is missing. */
export function readPointer(document: unknown, pointer: string): unknown {
  let node = document
  for (const raw of pointer.slice(1).split('/')) {
    if (typeof node !== 'object' || node === null) return undefined
    const key = raw.replaceAll('~1', '/').replaceAll('~0', '~')
    node = Object.hasOwn(node, key) ? (node as Record<string, unknown>)[key] : undefined
  }
  return node
}

/** `/queue/parallel_jobs` → `queue.parallel_jobs`, the path the server's issues use. */
export function pathOfPointer(pointer: string): string {
  return pointer.slice(1).replaceAll('/', '.')
}

type Translate = ReturnType<typeof useI18n>['t']

/**
 * Why the server refused a settings change, as issues for the field at `path`. A refusal
 * without issues (a 403 of web mode, an unreachable server) becomes one issue from its text.
 */
export function refusalIssues(error: ApiError, path: string, t: Translate): ValidationIssue[] {
  const issues = error.problem.issues ?? []
  if (issues.length > 0) return issues
  const { title, detail, code } = error.problem
  const message = detail ? t('settings.refusedWithDetail', { title, detail }) : title
  return [{ severity: 'error', code, path, message, fixes: [] }]
}

/**
 * The server's settings file is newer than the server or unreadable: a change would hold only
 * until the server stops, so the settings are shown read-only.
 */
export function useSettingsLocked(): ComputedRef<boolean> {
  const system = useSystemStore()
  return computed(() => system.info?.settings_read_only === true)
}

export interface SettingControl<T> {
  /** The refused value while its refusal shows, else the server's. */
  value: ComputedRef<T | undefined>
  issues: ComputedRef<ValidationIssue[]>
  saving: ComputedRef<boolean>
  /** Saves at once; `false` when the server refused (the issue shows at the field). */
  save(next: T): Promise<boolean>
}

/** One setting, saved at once with `settings.set`; a refusal stays at the field until the next save. */
export function useSetting<T>(pointer: string): SettingControl<T> {
  const { t } = useI18n()
  const store = useSettingsStore()
  const refused = shallowRef<{ value: T; issues: ValidationIssue[] } | null>(null)
  const pending = ref(0)

  const value = computed(() =>
    refused.value === null
      ? (readPointer(store.settings, pointer) as T | undefined)
      : refused.value.value,
  )

  async function save(next: T): Promise<boolean> {
    pending.value += 1
    try {
      await store.set(pointer, next)
      refused.value = null
      return true
    } catch (error) {
      if (!(error instanceof ApiError)) throw error
      refused.value = { value: next, issues: refusalIssues(error, pathOfPointer(pointer), t) }
      return false
    } finally {
      pending.value -= 1
    }
  }

  return {
    value,
    issues: computed(() => refused.value?.issues ?? []),
    saving: computed(() => pending.value > 0),
    save,
  }
}
