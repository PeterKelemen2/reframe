// oxlint-disable unicorn/consistent-function-scoping -- stub actions; they use the store once built
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { notBuilt } from '@/notBuilt'

export type DefaultsKind = 'audio' | 'subtitles'

/**
 * Whose defaults the dialog edits: the open job's (from its preset), a preset's, or a batch
 * group's. The group target is typed for the batch UI and not built yet.
 */
export type DefaultsTarget =
  | { kind: 'job' }
  | { kind: 'preset'; presetId: string }
  | { kind: 'group'; groupId: string }

/** The audio and subtitle defaults dialog: what it edits, and whether it is open. */
export const useDefaultsStore = defineStore('defaults', () => {
  const visible = ref(false)
  const kind = ref<DefaultsKind>('audio')
  const target = ref<DefaultsTarget | null>(null)

  async function open(which: DefaultsKind, whose: DefaultsTarget): Promise<void> {
    return notBuilt('defaults.open', which, whose)
  }

  /** Closes without applying. */
  function close(): void {
    notBuilt('defaults.close')
  }

  return { visible, kind, target, open, close }
})
