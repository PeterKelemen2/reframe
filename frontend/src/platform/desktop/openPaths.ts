import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { ask, open } from '@tauri-apps/plugin-dialog'

import { createAppI18n } from '@/i18n'

export const OPEN_PATHS_EVENT = 'open-paths'

/** What the app gives for a name that is not valid Unicode: that path does not exist. */
const UNREADABLE = String.fromCodePoint(0xfffd)

function failed(error: unknown): void {
  console.error('platform.onOpenPaths failed', error)
}

/** Says which paths cannot be read, and offers the file dialog for them instead. */
async function offerFileDialog(unreadable: string[], cb: (paths: string[]) => void) {
  const { t } = createAppI18n().global
  const n = unreadable.length
  const chosen = await ask(t('openPaths.unreadable.text', { n, paths: unreadable.join('\n') }), {
    title: t('openPaths.unreadable.title', { n }),
    kind: 'warning',
    okLabel: t('openPaths.unreadable.openFiles'),
    cancelLabel: t('openPaths.unreadable.cancel'),
  })
  if (!chosen) return
  const picked = await open({ multiple: true, directory: false })
  if (picked !== null && picked.length > 0) cb(picked)
}

/**
 * The paths that wait in the app (the command line's, a second launch's), then each new batch.
 * Only in the main window: each path is taken once, and the preview window would take them.
 */
export function onOpenPaths(cb: (paths: string[]) => void): () => void {
  if (getCurrentWindow().label !== 'main') return () => {}
  let stopped = false
  let unlisten: UnlistenFn | null = null

  const take = async (): Promise<void> => {
    const paths = await invoke<string[]>('take_open_paths')
    if (stopped) return
    const readable = paths.filter((path) => !path.includes(UNREADABLE))
    const unreadable = paths.filter((path) => path.includes(UNREADABLE))
    if (readable.length > 0) cb(readable)
    if (unreadable.length > 0) await offerFileDialog(unreadable, cb)
  }
  listen(OPEN_PATHS_EVENT, () => void take().catch(failed))
    .then((stop) => {
      if (stopped) return stop()
      unlisten = stop
      // Only once the listener is on: a path that came before it waits, and one after it is an event.
      return take()
    })
    .catch(failed)

  return () => {
    stopped = true
    void unlisten?.()
  }
}
