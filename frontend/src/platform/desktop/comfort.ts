import type { DesktopSettings } from '../types'

// Stub until the desktop settings and the preview window land: the defaults, nothing saved.
export function settings(): Promise<DesktopSettings> {
  return Promise.resolve({ tray: false })
}

export function setSettings(next: DesktopSettings): Promise<DesktopSettings> {
  return Promise.resolve(next)
}

export function openPreviewWindow(_sourceId: string): Promise<void> {
  return Promise.reject(new Error('not available in this build yet'))
}
