import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'
import { getCurrentWebview } from '@tauri-apps/api/webview'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { ask, open, save } from '@tauri-apps/plugin-dialog'
import { requestPermission, sendNotification } from '@tauri-apps/plugin-notification'
import { openUrl, revealItemInDir } from '@tauri-apps/plugin-opener'

import { createAppI18n } from '@/i18n'

import type {
  DesktopBackend,
  DesktopBackendError,
  DesktopBackendState,
  DesktopShell,
  Platform,
} from '../types'

import { openPreviewWindow, setSettings, settings } from './comfort'
import { onOpenPaths } from './openPaths'

export const BACKEND_STATE_EVENT = 'backend-state'
export const QUIT_EVENT = 'quit-requested'

/** What a file manager sends for a name that is not UTF-8: that path does not exist. */
const UNREADABLE = String.fromCodePoint(0xfffd)

/** Turns the listener a Tauri call gives later into the unsubscribe the callers want now. */
function subscribe(listening: Promise<UnlistenFn>): () => void {
  let stopped = false
  let unlisten: UnlistenFn | null = null
  void listening.then((stop) => {
    if (stopped) return stop()
    unlisten = stop
    return undefined
  })
  return () => {
    stopped = true
    void unlisten?.()
  }
}

function backendError(error: unknown): DesktopBackendError {
  if (typeof error === 'object' && error !== null && 'message' in error) {
    return error as DesktopBackendError
  }
  // An IPC failure (a command the window may not call) rejects with a plain string.
  return { message: String(error), log: null }
}

async function backendInfo(): Promise<DesktopBackend> {
  try {
    return await invoke<DesktopBackend>('backend_info')
  } catch (error) {
    throw backendError(error)
  }
}

/** The preview window loads the same page: only the main window's page answers a close. */
function inMainWindow(): boolean {
  return getCurrentWindow().label === 'main'
}

/** `.MKV` and `mkv` both mean the extension `mkv`. */
function dialogFilters(filters: string[] | undefined) {
  if (filters === undefined || filters.length === 0) return undefined
  const extensions = filters.map((ext) => ext.replace(/^\./, '').toLowerCase())
  return [{ name: extensions.map((ext) => `*.${ext}`).join(' '), extensions }]
}

async function pickFiles({
  multiple,
  filters,
}: {
  multiple: boolean
  filters?: string[]
}): Promise<string[]> {
  const chosen = await open({ multiple, directory: false, filters: dialogFilters(filters) })
  if (chosen === null) return []
  return Array.isArray(chosen) ? chosen : [chosen]
}

/** Says which dropped names cannot be read, and offers the file dialog for them instead. */
async function offerFileDialog(unreadable: string[], cb: (paths: string[]) => void) {
  const { t } = createAppI18n().global
  const names = unreadable.map((path) => path.split(/[\\/]/).pop() ?? path)
  const chosen = await ask(t('desktop.drop.unreadable', { names: names.join('\n') }), {
    title: t('desktop.drop.title'),
    kind: 'warning',
    okLabel: t('desktop.drop.openFiles'),
    cancelLabel: t('desktop.drop.cancel'),
  })
  if (!chosen) return
  const paths = await pickFiles({ multiple: true })
  if (paths.length > 0) cb(paths)
}

export function createDesktopPlatform(): Platform {
  const desktop: DesktopShell = {
    backendInfo,

    onBackendState(cb) {
      return subscribe(
        listen<DesktopBackendState>(BACKEND_STATE_EVENT, (event) => cb(event.payload)),
      )
    },

    retryBackend() {
      return invoke('backend_retry')
    },

    onQuitRequested(cb) {
      if (!inMainWindow()) return () => {}
      return subscribe(listen(QUIT_EVENT, () => cb()))
    },

    async quitReady() {
      if (inMainWindow()) await invoke('quit_ready')
    },

    quit() {
      return invoke('quit_app')
    },

    hideMainWindow() {
      return invoke('hide_main_window')
    },

    onOpenPaths,
    settings,
    setSettings,
    openPreviewWindow,
  }

  return {
    kind: 'desktop',

    async backend() {
      const { baseUrl, token } = await backendInfo()
      return { baseUrl, token }
    },

    pickFiles,

    pickFolder(options) {
      return open({ directory: true, multiple: false, title: options?.title })
    },

    pickSavePath({ defaultPath }) {
      return save({ defaultPath })
    },

    onFilesDropped(cb) {
      return subscribe(
        getCurrentWebview().onDragDropEvent((event) => {
          if (event.payload.type !== 'drop') return
          const readable = event.payload.paths.filter((path) => !path.includes(UNREADABLE))
          const unreadable = event.payload.paths.filter((path) => path.includes(UNREADABLE))
          if (readable.length > 0) cb(readable)
          if (unreadable.length > 0) {
            offerFileDialog(unreadable, cb).catch((error: unknown) =>
              console.error('platform.onFilesDropped failed', error),
            )
          }
        }),
      )
    },

    revealInFolder(path) {
      return revealItemInDir(path)
    },

    openExternal(target) {
      return openUrl(target)
    },

    async notify(title, body) {
      // Resolves at once on the desktop, where no one is asked.
      if ((await requestPermission()) === 'granted') sendNotification({ title, body })
    },

    setTaskbarProgress(value) {
      invoke('set_taskbar_progress', { value }).catch((error: unknown) =>
        console.error('platform.setTaskbarProgress failed', error),
      )
    },

    desktop,
  }
}
