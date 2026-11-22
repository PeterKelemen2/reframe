import { emit } from '@tauri-apps/api/event'
import { clearMocks, mockIPC, mockWindows } from '@tauri-apps/api/mocks'
import type { InvokeArgs } from '@tauri-apps/api/core'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { DesktopBackendState } from '../types'

import { BACKEND_STATE_EVENT, QUIT_EVENT, createDesktopPlatform } from './index'

interface Call {
  cmd: string
  args: InvokeArgs | undefined
}

let calls: Call[]
let answers: Record<string, (args: InvokeArgs | undefined) => unknown>

/** The app's Rust side: each command answers from `answers`; events are delivered in the page. */
function shell(window = 'main') {
  calls = []
  answers = {}
  mockWindows(window)
  mockIPC(
    (cmd, args) => {
      calls.push({ cmd, args })
      const answer = answers[cmd]
      return answer === undefined ? null : answer(args)
    },
    { shouldMockEvents: true },
  )
  return createDesktopPlatform()
}

function sent(cmd: string): (InvokeArgs | undefined)[] {
  return calls.filter((call) => call.cmd === cmd).map((call) => call.args)
}

/** Tauri sends a drag-and-drop to the webview as these events. */
async function drag(type: 'enter' | 'over' | 'drop' | 'leave', paths: string[] = []) {
  await emit(`tauri://drag-${type}`, { paths, position: { x: 10, y: 10 } })
  await flushPromises()
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  clearMocks()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('the desktop backend', () => {
  const info = { baseUrl: 'http://127.0.0.1:8731', token: 't0k', instance: 'i1', owned: true }

  it('gives the address and token of the backend', async () => {
    const platform = shell()
    answers.backend_info = () => info
    await expect(platform.backend()).resolves.toEqual({ baseUrl: info.baseUrl, token: 't0k' })
    await expect(platform.desktop!.backendInfo()).resolves.toEqual(info)
  })

  it('rejects with the backend error, and makes a plain IPC failure one', async () => {
    const platform = shell()
    const error = { message: 'The sidecar did not start', log: '/data/logs/sidecar.log' }
    answers.backend_info = () => Promise.reject(error)
    await expect(platform.desktop!.backendInfo()).rejects.toEqual(error)
    answers.backend_info = () => Promise.reject('backend_info not allowed')
    await expect(platform.desktop!.backendInfo()).rejects.toEqual({
      message: 'backend_info not allowed',
      log: null,
    })
  })

  it('hears each backend state until unsubscribed', async () => {
    const platform = shell()
    const states: DesktopBackendState[] = []
    const stop = platform.desktop!.onBackendState((state) => states.push(state))
    await flushPromises()
    await emit(BACKEND_STATE_EVENT, { state: 'starting' })
    await emit(BACKEND_STATE_EVENT, { state: 'ready', info })
    expect(states).toEqual([{ state: 'starting' }, { state: 'ready', info }])
    stop()
    await emit(BACKEND_STATE_EVENT, { state: 'starting' })
    expect(states).toHaveLength(2)
  })

  it('does not listen when unsubscribed before the listener is in place', async () => {
    const platform = shell()
    const states: DesktopBackendState[] = []
    platform.desktop!.onBackendState((state) => states.push(state))()
    await flushPromises()
    await emit(BACKEND_STATE_EVENT, { state: 'starting' })
    expect(states).toEqual([])
  })

  it('logs a listener the app refuses', async () => {
    const platform = shell()
    mockIPC((cmd) =>
      cmd === 'plugin:event|listen' ? Promise.reject('event.listen not allowed') : null,
    )
    platform.desktop!.onBackendState(() => {})
    await flushPromises()
    expect(console.error).toHaveBeenCalledWith(
      'platform.onBackendState failed',
      'event.listen not allowed',
    )
  })

  it('asks the shell to start the backend again', async () => {
    const platform = shell()
    await platform.desktop!.retryBackend()
    expect(sent('backend_retry')).toHaveLength(1)
  })
})

describe('quitting', () => {
  it('answers a close in the main window once it says it can', async () => {
    const platform = shell('main')
    const requested = vi.fn<() => void>()
    platform.desktop!.onQuitRequested(requested)
    await platform.desktop!.quitReady()
    await flushPromises()
    await emit(QUIT_EVENT)
    expect(requested).toHaveBeenCalledOnce()
    expect(sent('quit_ready')).toHaveLength(1)
  })

  it('leaves the close to the main window in the preview window', async () => {
    const platform = shell('preview')
    const requested = vi.fn<() => void>()
    platform.desktop!.onQuitRequested(requested)
    await platform.desktop!.quitReady()
    await flushPromises()
    await emit(QUIT_EVENT)
    expect(requested).not.toHaveBeenCalled()
    expect(sent('quit_ready')).toEqual([])
  })

  it('leaves quitting and notifying to the main window in the preview window', async () => {
    const platform = shell('preview')
    const shown = notifications('granted')
    await platform.desktop!.quit()
    await platform.notify('Job done', 'a.mkv')
    expect(sent('quit_app')).toEqual([])
    expect(shown).toEqual([])
  })

  it('quits, and hides the window, through the shell, with its failure', async () => {
    const platform = shell()
    await platform.desktop!.quit()
    expect(sent('quit_app')).toHaveLength(1)
    answers.hide_main_window = () => Promise.reject('no main window')
    await expect(platform.desktop!.hideMainWindow()).rejects.toBe('no main window')
  })
})

describe('the native dialogs', () => {
  it('opens files with the callers’ extensions as the filter', async () => {
    const platform = shell()
    answers['plugin:dialog|open'] = () => ['/m/a.srt', '/m/b.ass']
    const paths = await platform.pickFiles({ multiple: true, filters: ['.SRT', 'ass'] })
    expect(paths).toEqual(['/m/a.srt', '/m/b.ass'])
    expect(sent('plugin:dialog|open')).toEqual([
      {
        options: {
          multiple: true,
          directory: false,
          filters: [{ name: '*.srt *.ass', extensions: ['srt', 'ass'] }],
        },
      },
    ])
  })

  it('gives one file as a list, every file without a filter, and nothing when cancelled', async () => {
    const platform = shell()
    answers['plugin:dialog|open'] = () => '/m/chapters.xml'
    expect(await platform.pickFiles({ multiple: false })).toEqual(['/m/chapters.xml'])
    expect(sent('plugin:dialog|open')[0]).toEqual({
      options: { multiple: false, directory: false },
    })
    answers['plugin:dialog|open'] = () => null
    expect(await platform.pickFiles({ multiple: true })).toEqual([])
  })

  it('chooses a folder with its title, or nothing', async () => {
    const platform = shell()
    answers['plugin:dialog|open'] = () => '/srv/out'
    expect(await platform.pickFolder({ title: 'Output folder' })).toBe('/srv/out')
    expect(sent('plugin:dialog|open')[0]).toEqual({
      options: { directory: true, multiple: false, title: 'Output folder' },
    })
    answers['plugin:dialog|open'] = () => null
    expect(await platform.pickFolder()).toBeNull()
  })

  it('chooses a path to save from the default one', async () => {
    const platform = shell()
    answers['plugin:dialog|save'] = () => '/srv/out/b.mkv'
    expect(await platform.pickSavePath({ defaultPath: '/srv/out/a.mkv' })).toBe('/srv/out/b.mkv')
    expect(sent('plugin:dialog|save')).toEqual([{ options: { defaultPath: '/srv/out/a.mkv' } }])
  })
})

describe('drag and drop', () => {
  it('gives the dropped paths, and nothing for the drag before the drop', async () => {
    const platform = shell()
    const dropped = vi.fn<(paths: string[]) => void>()
    platform.onFilesDropped(dropped)
    await flushPromises()
    await drag('enter', ['/m/a.mkv'])
    await drag('over')
    expect(dropped).not.toHaveBeenCalled()
    await drag('drop', ['/m/Ünnepi film – 2.mkv', '/m/season'])
    expect(dropped).toHaveBeenCalledExactlyOnceWith(['/m/Ünnepi film – 2.mkv', '/m/season'])
  })

  it('reports a name that cannot be read and opens the file dialog for it', async () => {
    const platform = shell()
    const dropped = vi.fn<(paths: string[]) => void>()
    platform.onFilesDropped(dropped)
    await flushPromises()
    answers['plugin:dialog|message'] = () => 'Open files…'
    answers['plugin:dialog|open'] = () => ['/m/bad\xffname.mkv']
    await drag('drop', ['/m/a.mkv', '/m/bad\uFFFDname.mkv'])
    expect(dropped.mock.calls).toEqual([[['/m/a.mkv']], [['/m/bad\xffname.mkv']]])
    const [question] = sent('plugin:dialog|message')
    expect(question).toMatchObject({
      kind: 'warning',
      buttons: { OkCancelCustom: expect.anything() },
    })
    expect(String((question as { message: string }).message)).toContain('bad\uFFFDname.mkv')
    expect(sent('plugin:dialog|open')).toHaveLength(1)
  })

  it('opens no file dialog when the user declines', async () => {
    const platform = shell()
    const dropped = vi.fn<(paths: string[]) => void>()
    platform.onFilesDropped(dropped)
    await flushPromises()
    answers['plugin:dialog|message'] = () => 'Cancel'
    await drag('drop', ['/m/bad\uFFFDname.mkv'])
    expect(sent('plugin:dialog|message')).toHaveLength(1)
    expect(sent('plugin:dialog|open')).toEqual([])
    expect(dropped).not.toHaveBeenCalled()
  })
})

// The notification plugin's page script replaces `Notification`; this stands in for it.
function notifications(permission: NotificationPermission) {
  const shown: unknown[] = []
  class PluginNotification {
    static permission: NotificationPermission = 'default'
    static requestPermission = () => Promise.resolve(permission)
    constructor(title: string, options: NotificationOptions) {
      shown.push({ title, body: options.body })
    }
  }
  vi.stubGlobal('Notification', PluginNotification)
  return shown
}

describe('the other native integrations', () => {
  it('reveals a path in the file manager and opens a link outside', async () => {
    const platform = shell()
    await platform.revealInFolder('/out/a (1).mkv')
    expect(sent('plugin:opener|reveal_item_in_dir')).toEqual([{ paths: ['/out/a (1).mkv'] }])
    await platform.openExternal('http://127.0.0.1:8731/api/preview/clips/c1?sig=x')
    // Through the shell, which starts the player with the user's environment, not the AppImage's.
    expect(sent('plugin:opener|open_url')).toEqual([])
    expect(sent('open_external')).toEqual([
      { url: 'http://127.0.0.1:8731/api/preview/clips/c1?sig=x' },
    ])
  })

  it('sends a notification when allowed', async () => {
    const platform = shell()
    const shown = notifications('granted')
    await platform.notify('Queue done', '3 jobs')
    expect(shown).toEqual([{ title: 'Queue done', body: '3 jobs' }])
  })

  it('sends nothing when notifications are refused', async () => {
    const platform = shell()
    const refused = notifications('denied')
    await platform.notify('Job done', 'a.mkv')
    expect(refused).toEqual([])
  })

  it('asks the shell whether the window can play video, and assumes it can when the ask fails', async () => {
    const platform = shell()
    answers.webview_plays_video = () => false
    expect(await platform.canPlayVideo()).toBe(false)
    answers.webview_plays_video = () => true
    expect(await platform.canPlayVideo()).toBe(true)
    answers.webview_plays_video = () => Promise.reject('not allowed')
    expect(await platform.canPlayVideo()).toBe(true)
    expect(console.error).toHaveBeenCalled()
  })

  it('puts the progress on the taskbar, and a failure there breaks nothing', async () => {
    const platform = shell()
    platform.setTaskbarProgress(0.42, '42%')
    platform.setTaskbarProgress(null, null)
    expect(sent('set_taskbar_progress')).toEqual([{ value: 0.42 }, { value: null }])
    answers.set_taskbar_progress = () => Promise.reject('no window')
    expect(() => platform.setTaskbarProgress(0.5, '50%')).not.toThrow()
    await flushPromises()
    expect(console.error).toHaveBeenCalled()
  })
})
