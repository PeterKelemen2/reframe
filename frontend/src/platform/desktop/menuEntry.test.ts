import { clearMocks, mockIPC } from '@tauri-apps/api/mocks'
import { afterEach, describe, expect, it } from 'vitest'

import { menuEntry, setMenuEntry } from './menuEntry'

afterEach(() => clearMocks())

describe('the AppImage’s menu entry in the shell', () => {
  it('reads and changes the entry through the shell’s commands', async () => {
    const calls: unknown[] = []
    const entry = {
      appimage: '/a/Reframe.AppImage',
      added: true,
      other: null,
      percentInPath: false,
    }
    mockIPC((cmd, args) => {
      calls.push({ cmd, args })
      return entry
    })
    await expect(menuEntry()).resolves.toEqual(entry)
    await expect(setMenuEntry(true)).resolves.toEqual(entry)
    expect(calls).toEqual([
      { cmd: 'menu_entry', args: {} },
      { cmd: 'set_menu_entry', args: { add: true } },
    ])
  })
})
