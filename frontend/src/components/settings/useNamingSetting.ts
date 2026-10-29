import { computed, onScopeDispose, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { JsonPatchOp, NamingOptions, ValidationIssue } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'

import { refusalIssues } from './useSetting'

/** Typing in a template emits a new object per key: one save per pause. */
export const NAMING_SAVE_DELAY = 600

const POINTER = '/output/naming'

/** One op per member of `next` that differs from `saved` (`add` for one `saved` lacks). */
export function namingOps(saved: NamingOptions, next: NamingOptions): JsonPatchOp[] {
  const ops: JsonPatchOp[] = []
  for (const [key, value] of Object.entries(next)) {
    const before = (saved as Record<string, unknown>)[key]
    if (Object.hasOwn(saved, key) && JSON.stringify(before) === JSON.stringify(value)) continue
    const op = Object.hasOwn(saved, key) ? 'replace' : 'add'
    ops.push({ op, path: `${POINTER}/${key}`, value } as JsonPatchOp)
  }
  return ops
}

/**
 * The naming options of Settings → Output. Edits show at once and are saved after a pause, the
 * changed members only; a refused edit stays shown with the server's reason. Leaving the page
 * saves an edit that is still waiting.
 */
export function useNamingSetting() {
  const { t } = useI18n()
  const store = useSettingsStore()
  const draft = shallowRef<NamingOptions | null>(null)
  const issues = shallowRef<ValidationIssue[]>([])
  let timer: ReturnType<typeof setTimeout> | undefined

  const saved = computed(() => store.settings?.output?.naming ?? null)
  const naming = computed(() => draft.value ?? saved.value)

  async function flush(): Promise<void> {
    clearTimeout(timer)
    timer = undefined
    const sending = draft.value
    const base = saved.value
    if (sending === null || base === null) return
    const ops = namingOps(base, sending)
    if (ops.length > 0) {
      try {
        await store.update(ops)
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
        issues.value = refusalIssues(error, 'output.naming', t)
        return
      }
    }
    issues.value = []
    // A newer edit came while this one was saved: it has its own save scheduled.
    if (draft.value === sending) draft.value = null
  }

  function edit(next: NamingOptions): void {
    draft.value = next
    clearTimeout(timer)
    timer = setTimeout(() => void flush(), NAMING_SAVE_DELAY)
  }

  onScopeDispose(() => {
    if (timer !== undefined) void flush()
  })

  return { naming, issues, edit, flush }
}
