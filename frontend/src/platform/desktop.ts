import type { Platform } from './types'

// D-4 implements this with the Tauri plugins. Until then it imports nothing from Tauri, and
// every call fails loudly.
const MESSAGE = 'not implemented (D-4)'

function reject(): Promise<never> {
  return Promise.reject(new Error(MESSAGE))
}

function fail(): never {
  throw new Error(MESSAGE)
}

export function createDesktopPlatform(): Platform {
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
  }
}
