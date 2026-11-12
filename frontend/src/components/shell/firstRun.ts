import { useLocalStorage } from '@vueuse/core'
import { computed } from 'vue'

import { platform } from '@/platform'
import { useSystemStore } from '@/stores/system'

/**
 * Set once the desktop app's first start has been continued. Losing it only shows the tools
 * once more, so this webview's storage is enough.
 */
export const FIRST_RUN_KEY = 'reframe.firstRun.seen'

/** Whether the first-run screen replaces the workspace, and why. */
export function useFirstRun() {
  const system = useSystemStore()
  const seen = useLocalStorage(FIRST_RUN_KEY, false, { writeDefaults: false })

  /** The desktop app's first start, once the tools are known: they show even when they work. */
  const firstStart = computed(
    () => platform.kind === 'desktop' && !seen.value && system.info !== null,
  )
  const shown = computed(() => system.ffmpegProblem !== null || firstStart.value)

  function finish(): void {
    seen.value = true
  }

  return { firstStart, shown, finish }
}
