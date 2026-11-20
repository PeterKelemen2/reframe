import { invoke } from '@tauri-apps/api/core'

import type { DesktopMenuEntry } from '../types'

export function menuEntry(): Promise<DesktopMenuEntry> {
  return invoke<DesktopMenuEntry>('menu_entry')
}

export function setMenuEntry(add: boolean): Promise<DesktopMenuEntry> {
  return invoke<DesktopMenuEntry>('set_menu_entry', { add })
}
