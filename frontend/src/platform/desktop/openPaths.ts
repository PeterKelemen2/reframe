import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { getCurrentWindow } from '@tauri-apps/api/window'

import { subscribe } from './subscribe'
import { openReadable } from './unreadable'

export const OPEN_PATHS_EVENT = 'open-paths'

function failed(error: unknown): void {
  console.error('platform.onOpenPaths failed', error)
}

/**
 * The paths that wait in the app (the command line's, a second launch's), then each new batch.
 * Only in the main window: each path is taken once, and the preview window would take them.
 */
export function onOpenPaths(cb: (paths: string[]) => void): () => void {
  if (getCurrentWindow().label !== 'main') return () => {}
  let stopped = false

  // A path taken after the unsubscribe would be lost: it is taken only once.
  const take = async (): Promise<void> => {
    if (stopped) return
    const paths = await invoke<string[]>('take_open_paths')
    if (stopped) return
    await openReadable(paths, cb)
  }
  const unsubscribe = subscribe(
    'platform.onOpenPaths',
    listen(OPEN_PATHS_EVENT, () => void take().catch(failed)).then((stop) => {
      // Only once the listener is on: a path that came before it waits, and one after it is an event.
      take().catch(failed)
      return stop
    }),
  )
  return () => {
    stopped = true
    unsubscribe()
  }
}
