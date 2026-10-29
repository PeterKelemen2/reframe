// oxlint-disable unicorn/consistent-function-scoping -- stub actions; they use the store once built
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { AppSettings, JsonPatchOp, SettingsChange } from '@/api/types'
import { notBuilt } from '@/notBuilt'

/** The server's settings (`GET/PUT /api/settings`). */
export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<AppSettings | null>(null)
  const loaded = ref(false)

  async function load(): Promise<void> {
    return notBuilt('settings.load')
  }

  /**
   * Applies a JSON patch on the server and keeps the answer. A refused patch rejects with an
   * `ApiError` and is not toasted: the caller shows it at its field.
   */
  async function update(ops: JsonPatchOp[]): Promise<SettingsChange> {
    return notBuilt('settings.update', ops)
  }

  /** `update` with one `replace` (an `add` where the member is missing). */
  async function set(pointer: string, value: unknown): Promise<SettingsChange> {
    return notBuilt('settings.set', pointer, value)
  }

  return { settings, loaded, load, update, set }
})
