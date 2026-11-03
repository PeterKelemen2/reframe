import type { DesktopShell, Platform } from '../types'

import { settings, setSettings, openPreviewWindow } from './comfort'
import { onOpenPaths } from './openPaths'

// Stub until the desktop adapter lands: every call fails loudly.
const MESSAGE = 'not available in this build yet'

function reject(): Promise<never> {
  return Promise.reject(new Error(MESSAGE))
}

function fail(): never {
  throw new Error(MESSAGE)
}

export function createDesktopPlatform(): Platform {
  const desktop: DesktopShell = {
    backendInfo: reject,
    onBackendState: fail,
    retryBackend: reject,
    onQuitRequested: fail,
    quitReady: reject,
    quit: reject,
    hideMainWindow: reject,
    onOpenPaths,
    settings,
    setSettings,
    openPreviewWindow,
  }
  return {
    kind: 'desktop',
    backend: reject,
    pickFiles: reject,
    pickFolder: reject,
    pickSavePath: reject,
    onFilesDropped: fail,
    revealInFolder: reject,
    openExternal: reject,
    notify: reject,
    setTaskbarProgress: fail,
    desktop,
  }
}
