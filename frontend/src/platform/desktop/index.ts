import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { getCurrentWebview } from '@tauri-apps/api/webview'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { open, save } from '@tauri-apps/plugin-dialog'
import { requestPermission, sendNotification } from '@tauri-apps/plugin-notification'
import { revealItemInDir } from '@tauri-apps/plugin-opener'

import type {
  DesktopBackend,
  DesktopBackendError,
  DesktopBackendState,
  DesktopShell,
  Platform,
} from '../types'

import { openPreviewWindow, setSettings, settings } from './comfort'
import { onOpenPaths } from './openPaths'
import { subscribe } from './subscribe'
import { openReadable } from './unreadable'

export const BACKEND_STATE_EVENT = 'backend-state'
export const QUIT_EVENT = 'quit-requested'

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

/**
 * The preview window loads the same page: only the main window's page answers a close, quits
 * (a when-done quit) and notifies, and the preview window may not call those commands.
 */
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

export function createDesktopPlatform(): Platform {
  const desktop: DesktopShell = {
    backendInfo,

    onBackendState(cb) {
      return subscribe(
        'platform.onBackendState',
        listen<DesktopBackendState>(BACKEND_STATE_EVENT, (event) => cb(event.payload)),
      )
    },

    retryBackend() {
      return invoke('backend_retry')
    },

    onQuitRequested(cb) {
      if (!inMainWindow()) return () => {}
      return subscribe(
        'platform.onQuitRequested',
        listen(QUIT_EVENT, () => cb()),
      )
    },

    async quitReady() {
      if (inMainWindow()) await invoke('quit_ready')
    },

    async quit() {
      if (inMainWindow()) await invoke('quit_app')
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
        'platform.onFilesDropped',
        getCurrentWebview().onDragDropEvent((event) => {
          if (event.payload.type !== 'drop') return
          openReadable(event.payload.paths, cb).catch((error: unknown) =>
            console.error('platform.onFilesDropped failed', error),
          )
        }),
      )
    },

    revealInFolder(path) {
      return revealItemInDir(path)
    },

    openExternal(target) {
      return invoke('open_external', { url: target })
    },

    async canPlayVideo() {
      try {
        return await invoke<boolean>('webview_plays_video')
      } catch (error) {
        console.error('platform.canPlayVideo failed', error)
        return true
      }
    },

    async notify(title, body) {
      if (!inMainWindow()) return
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
