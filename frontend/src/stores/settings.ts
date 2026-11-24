import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, apiQuiet, unwrap } from '@/api/client'
import type { AppSettings, JsonPatchOp, SettingsChange } from '@/api/types'

/** Whether `pointer` (RFC 6901) names a member that `document` has. */
export function hasPointer(document: unknown, pointer: string): boolean {
  if (pointer === '') return true
  let node = document
  for (const raw of pointer.slice(1).split('/')) {
    const key = raw.replaceAll('~1', '/').replaceAll('~0', '~')
    if (typeof node !== 'object' || node === null || !Object.hasOwn(node, key)) return false
    node = (node as Record<string, unknown>)[key]
  }
  return true
}

/** The server's settings (`GET/PUT /api/settings`). */
export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<AppSettings | null>(null)
  const loaded = ref(false)
  /** +1 for each change of the naming options (Settings → Output) that this client sees. */
  const namingRevision = ref(0)

  function keep(next: AppSettings): void {
    const before = settings.value?.output?.naming
    if (before !== undefined && JSON.stringify(before) !== JSON.stringify(next.output?.naming)) {
      namingRevision.value += 1
    }
    settings.value = next
  }

  // One request at a time: answers of concurrent requests could arrive out of order, and each
  // answer is the whole settings document.
  let chain: Promise<unknown> = Promise.resolve()
  function serial<T>(request: () => Promise<T>): Promise<T> {
    const next = chain.then(request, request)
    chain = next.catch(() => undefined)
    return next
  }

  async function load(): Promise<void> {
    return serial(async () => {
      keep(unwrap(await api.GET('/api/settings')))
      loaded.value = true
    })
  }

  /**
   * Applies a JSON patch on the server and keeps the answer. A refused patch rejects with an
   * `ApiError` and is not toasted: the caller shows it at its field.
   */
  async function update(ops: JsonPatchOp[]): Promise<SettingsChange> {
    return serial(async () => {
      const change = unwrap(await apiQuiet.PUT('/api/settings', { body: ops }))
      keep(change.settings)
      loaded.value = true
      return change
    })
  }

  /** `update` with one `replace` (an `add` where the member is missing). */
  async function set(pointer: string, value: unknown): Promise<SettingsChange> {
    const op = hasPointer(settings.value, pointer) ? 'replace' : 'add'
    return update([{ op, path: pointer, value } as JsonPatchOp])
  }

  return { settings, loaded, namingRevision, load, update, set }
})
