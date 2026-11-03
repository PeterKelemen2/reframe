import { emit } from '@tauri-apps/api/event'
import type { InvokeArgs } from '@tauri-apps/api/core'
import { clearMocks, mockIPC, mockWindows } from '@tauri-apps/api/mocks'
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { OPEN_PATHS_EVENT, onOpenPaths } from './openPaths'

let waiting: string[]
let takes: number
let dialogs: { cmd: string; args: InvokeArgs | undefined }[]
let answers: Record<string, unknown>
/** Runs while the app answers the page's first look. */
let duringFirstTake: (() => void) | null

/** The app's side: `take_open_paths` hands out what waits, once; the dialogs answer from `answers`. */
function shell(window = 'main') {
  waiting = []
  takes = 0
  dialogs = []
  answers = {}
  duringFirstTake = null
  mockWindows(window)
  mockIPC(
    (cmd, args) => {
      if (cmd === 'take_open_paths') {
        takes += 1
        const taken = waiting.splice(0)
        if (takes === 1) duringFirstTake?.()
        return taken
      }
      dialogs.push({ cmd, args })
      return answers[cmd] ?? null
    },
    { shouldMockEvents: true },
  )
}

/** A second launch: its paths wait in the app, which tells the main window. */
async function secondLaunch(...paths: string[]) {
  waiting.push(...paths)
  await emit(OPEN_PATHS_EVENT)
  await flushPromises()
}

beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => {}))

afterEach(() => {
  clearMocks()
  vi.restoreAllMocks()
})

describe('onOpenPaths', () => {
  it('gives the paths that waited before the page listened, then each handed-over batch', async () => {
    shell()
    waiting.push('/m/file1.mkv', '/m/folder')
    const opened = vi.fn<(paths: string[]) => void>()
    onOpenPaths(opened)
    await flushPromises()
    await secondLaunch('/m/other.mkv')
    expect(opened.mock.calls).toEqual([[['/m/file1.mkv', '/m/folder']], [['/m/other.mkv']]])
  })

  it('misses no path handed over just after the page first looked', async () => {
    shell()
    duringFirstTake = () => {
      waiting.push('/m/late.mkv')
      void emit(OPEN_PATHS_EVENT)
    }
    const opened = vi.fn<(paths: string[]) => void>()
    onOpenPaths(opened)
    await flushPromises()
    expect(opened.mock.calls).toEqual([[['/m/late.mkv']]])
  })

  it('gives nothing when nothing waits', async () => {
    shell()
    const opened = vi.fn<(paths: string[]) => void>()
    onOpenPaths(opened)
    await flushPromises()
    await emit(OPEN_PATHS_EVENT)
    await flushPromises()
    expect(opened).not.toHaveBeenCalled()
  })

  it('takes nothing in the preview window', async () => {
    shell('preview')
    waiting.push('/m/file1.mkv')
    const opened = vi.fn<(paths: string[]) => void>()
    onOpenPaths(opened)
    await secondLaunch('/m/other.mkv')
    expect(opened).not.toHaveBeenCalled()
    expect(takes).toBe(0)
  })

  it('stops when unsubscribed', async () => {
    shell()
    const opened = vi.fn<(paths: string[]) => void>()
    const stop = onOpenPaths(opened)
    await flushPromises()
    stop()
    await secondLaunch('/m/other.mkv')
    expect(opened).not.toHaveBeenCalled()
  })

  it('reports a name that cannot be read, opens the others, and gives what the file dialog picked', async () => {
    shell()
    answers['plugin:dialog|message'] = 'Open files…'
    answers['plugin:dialog|open'] = ['/m/bad\xffname.mkv']
    const opened = vi.fn<(paths: string[]) => void>()
    onOpenPaths(opened)
    await flushPromises()
    await secondLaunch('/m/a.mkv', '/m/bad\uFFFDname.mkv')
    expect(opened.mock.calls).toEqual([[['/m/a.mkv']], [['/m/bad\xffname.mkv']]])
    const [question, picker] = dialogs
    expect(question?.cmd).toBe('plugin:dialog|message')
    expect(question?.args).toMatchObject({
      title: 'A file name cannot be read',
      kind: 'warning',
      message: expect.stringContaining('/m/bad\uFFFDname.mkv'),
    })
    expect(picker).toEqual({
      cmd: 'plugin:dialog|open',
      args: { options: { multiple: true, directory: false } },
    })
  })

  it('names every unreadable path in one question, and opens nothing when declined', async () => {
    shell()
    answers['plugin:dialog|message'] = 'Cancel'
    const opened = vi.fn<(paths: string[]) => void>()
    onOpenPaths(opened)
    await flushPromises()
    await secondLaunch('/m/x\uFFFD.mkv', '/m/y\uFFFD.mkv')
    expect(dialogs.map((dialog) => dialog.cmd)).toEqual(['plugin:dialog|message'])
    expect(dialogs[0]?.args).toMatchObject({
      title: '2 file names cannot be read',
      message: expect.stringContaining('/m/x\uFFFD.mkv\n/m/y\uFFFD.mkv'),
    })
    expect(opened).not.toHaveBeenCalled()
  })
})
