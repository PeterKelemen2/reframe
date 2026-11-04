import type { InvokeArgs } from '@tauri-apps/api/core'
import { clearMocks, mockIPC } from '@tauri-apps/api/mocks'
import { afterEach, describe, expect, it } from 'vitest'

import { openPreviewWindow, setSettings, settings } from './comfort'

interface Call {
  cmd: string
  args: InvokeArgs | undefined
}

/** The Rust side: each command answers with `answer` (a thrown string is the command's error). */
function shell(answer: (cmd: string, args: InvokeArgs | undefined) => unknown): Call[] {
  const calls: Call[] = []
  mockIPC((cmd, args) => {
    calls.push({ cmd, args })
    return answer(cmd, args)
  })
  return calls
}

afterEach(() => clearMocks())

describe('the desktop shell’s settings and windows', () => {
  it('reads the shell’s settings', async () => {
    const calls = shell(() => ({ tray: true }))
    await expect(settings()).resolves.toEqual({ tray: true })
    expect(calls).toEqual([{ cmd: 'desktop_settings', args: {} }])
  })

  it('saves the settings and gives what the shell saved', async () => {
    const calls = shell(() => ({ tray: true }))
    await expect(setSettings({ tray: true })).resolves.toEqual({ tray: true })
    expect(calls).toEqual([{ cmd: 'set_desktop_settings', args: { settings: { tray: true } } }])
  })

  it('rejects with the shell’s reason when the settings cannot be applied', async () => {
    shell(() => {
      throw 'The tray needs the library libayatana-appindicator3'
    })
    await expect(setSettings({ tray: true })).rejects.toBe(
      'The tray needs the library libayatana-appindicator3',
    )
  })

  it('opens the preview window on the source', async () => {
    const calls = shell(() => null)
    await openPreviewWindow('3f9a0c4e1b2d')
    expect(calls).toEqual([{ cmd: 'open_preview_window', args: { sourceId: '3f9a0c4e1b2d' } }])
  })
})
