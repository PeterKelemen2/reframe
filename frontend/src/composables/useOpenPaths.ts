import { onScopeDispose, watch } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { platform } from '@/platform'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

/**
 * Opens the paths the desktop app was started with, or that a second launch handed over, in
 * the workspace once the app is ready. Does nothing in a browser.
 */
export function useOpenPaths(): void {
  const shell = platform.desktop
  if (shell === null) return
  const system = useSystemStore()
  const sources = useSourcesStore()
  const router = useRouter()
  const waiting: string[] = []

  const open = (): void => {
    if (system.phase !== 'ready' || waiting.length === 0) return
    const paths = waiting.splice(0)
    void router.push({ name: 'workspace' })
    const openAndShow = async (): Promise<void> => {
      // The file the user opened is shown, also when another one was.
      const [first] = await sources.open(paths, { select: false })
      if (first !== undefined) await sources.select(first.id)
    }
    openAndShow().catch((error: unknown) => {
      // A failed request is a toast already.
      if (!(error instanceof ApiError)) console.error('opening the paths failed', error)
    })
  }

  const stop = shell.onOpenPaths((paths) => {
    waiting.push(...paths)
    open()
  })
  watch(() => system.phase, open)
  onScopeDispose(stop)
}
