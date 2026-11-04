import { invoke } from '@tauri-apps/api/core'

import type { DesktopSettings } from '../types'

export function settings(): Promise<DesktopSettings> {
  return invoke<DesktopSettings>('desktop_settings')
}

/** Rejects with the shell's reason (a string) when the settings cannot be saved or applied. */
export function setSettings(next: DesktopSettings): Promise<DesktopSettings> {
  return invoke<DesktopSettings>('set_desktop_settings', { settings: next })
}

export function openPreviewWindow(sourceId: string): Promise<void> {
  return invoke('open_preview_window', { sourceId })
}
