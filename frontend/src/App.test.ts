import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { type App as VueApp, createApp } from 'vue'
import { createMemoryHistory } from 'vue-router'

import { desktopBackend } from '@/api/boot'
import type { QueueJob } from '@/api/types'
import App from '@/App.vue'
import { browse } from '@/components/sources/fileBrowser'
import { platform } from '@/platform'
import type { DesktopShell } from '@/platform/types'
import { createAppRouter } from '@/router'
import { installPlugins } from '@/setup'
import { type AppPhase, useSystemStore } from '@/stores/system'
import { useQueueStore } from '@/stores/queue'
import { useSourcesStore } from '@/stores/sources'

const openPaths = vi.hoisted(() => vi.fn<() => void>())
vi.mock('@/composables/useOpenPaths', () => ({ useOpenPaths: openPaths }))

let app: VueApp | undefined

// The real app with memory history instead of the URL; the phase is set before the mount, as
// the boot would.
async function mountApp(phase: AppPhase, path = '/', mode: 'token' | 'password' = 'token') {
  const router = createAppRouter(createMemoryHistory())
  const host = document.createElement('div')
  document.body.append(host)
  app = installPlugins(createApp(App), router)
  app.runWithContext(() => {
    const system = useSystemStore()
    system.phase = phase
    system.auth = { mode, authenticated: phase === 'ready' }
  })
  await router.push(path)
  await router.isReady()
  app.mount(host)
  await flushPromises()
  return { host, router }
}

function inPlaceJob(state: QueueJob['state']): QueueJob {
  return {
    id: 'edit',
    state,
    started_at: '2026-11-01T10:00:00Z',
    settings: { source: { path: '/media/a.mkv' }, output: { edit_in_place: true } },
  } as QueueJob
}

afterEach(() => {
  platform.desktop = null
  platform.kind = 'web'
  desktopBackend.value = null
  app?.unmount()
  app = undefined
  document.body.replaceChildren()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
})

describe('the app shell', () => {
  it('shows the boot screen while it connects, and says when the server cannot be reached', async () => {
    const { host } = await mountApp('booting')
    expect(host.textContent).toContain('Connecting to the Reframe server…')
    expect(host.querySelector('.nav-rail')).toBeNull()
    app?.runWithContext(() => (useSystemStore().phase = 'offline'))
    await flushPromises()
    expect(host.querySelector('h1')?.textContent).toBe('The Reframe server cannot be reached')
  })

  it('shows the login screen of the auth mode', async () => {
    const { host } = await mountApp('login', '/', 'password')
    expect(host.querySelector('.login-screen label')?.textContent).toBe('Password')
    expect(host.querySelector('.nav-rail')).toBeNull()
  })

  it('reaches every view from the navigation rail and marks the current one', async () => {
    const { host, router } = await mountApp('ready')
    expect(host.querySelector('.workspace')).not.toBeNull()
    async function visit(view: string): Promise<void> {
      host.querySelector<HTMLAnchorElement>(`.nav-rail__link[data-view="${view}"]`)?.click()
      await vi.waitFor(() => expect(router.currentRoute.value.name).toBe(view))
      await flushPromises()
      const current = [...host.querySelectorAll<HTMLElement>('[aria-current="page"]')]
      expect(current.map((link) => link.dataset.view)).toEqual([view])
    }
    await visit('queue')
    await visit('presets')
    await visit('activity')
    await visit('settings')
    await visit('workspace')
  })

  it('shows the when-done countdown with its Cancel above every view, and cancels it', async () => {
    const { host, router } = await mountApp('ready')
    const cancelPower = vi.fn<() => Promise<void>>(async () => {
      app?.runWithContext(() => (useQueueStore().power = null))
    })
    app?.runWithContext(() => {
      const queue = useQueueStore()
      vi.spyOn(queue, 'cancelPower').mockImplementation(cancelPower)
      queue.power = {
        type: 'power.countdown',
        countdown_id: 'p1',
        action: 'sleep',
        phase: 'tick',
        seconds_left: 58,
      } as never
    })
    await flushPromises()
    const banners = () => host.querySelectorAll('[data-component="power-banner"]')
    async function visit(view: string): Promise<void> {
      await router.push({ name: view })
      await flushPromises()
      expect(banners()).toHaveLength(1)
      expect(banners()[0]?.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
        'The queue is finished. When done: Sleep.',
      )
    }
    await visit('workspace')
    await visit('presets')
    await visit('settings')
    await visit('queue')
    const cancel = host.querySelector<HTMLButtonElement>('[data-action="cancel-power"]')
    cancel?.focus()
    cancel?.click()
    await flushPromises()
    expect(cancelPower).toHaveBeenCalledOnce()
    expect(banners()).toHaveLength(0)
    // The banner took its Cancel with it: the focus goes to the current view in the rail.
    expect(document.activeElement).toBe(host.querySelector('.nav-rail [aria-current="page"]'))

    // A countdown that ends elsewhere does not move a focus that was not on it.
    app?.runWithContext(() => {
      useQueueStore().power = {
        type: 'power.countdown',
        countdown_id: 'p2',
        action: 'sleep',
        phase: 'tick',
        seconds_left: 30,
      } as never
    })
    await flushPromises()
    ;(document.activeElement as HTMLElement | null)?.blur()
    app?.runWithContext(() => (useQueueStore().power = null))
    await flushPromises()
    expect(document.activeElement).toBe(document.body)
  })

  it('puts the progress of the running jobs on the taskbar', async () => {
    const setTaskbarProgress = vi.spyOn(platform, 'setTaskbarProgress')
    await mountApp('ready')
    expect(setTaskbarProgress).toHaveBeenLastCalledWith(null)
    app?.runWithContext(() => {
      useQueueStore().jobs = [
        { id: 'a', state: 'running', progress: { percent: 40 } } as QueueJob,
        { id: 'b', state: 'paused', progress: { percent: 60 } } as QueueJob,
      ]
    })
    await flushPromises()
    expect(setTaskbarProgress).toHaveBeenLastCalledWith(0.5)
  })

  it('reads an open source again when its in-place edit ends, whatever view is shown', async () => {
    await mountApp('ready', '/queue')
    const reload = app!.runWithContext(() => {
      const sources = useSourcesStore()
      sources.entries = [{ id: 's1', path: '/media/a.mkv', source: null } as never]
      const queue = useQueueStore()
      queue.loaded = true
      queue.jobs = [inPlaceJob('running')]
      return vi.spyOn(sources, 'reload').mockResolvedValue()
    })
    await flushPromises()
    app!.runWithContext(() => {
      useQueueStore().jobs = [inPlaceJob('done')]
    })
    await flushPromises()
    expect(reload).toHaveBeenCalledWith('s1')
  })

  it('shows the detached preview window without the app shell', async () => {
    vi.stubEnv('VITE_PLATFORM', 'desktop')
    const { host } = await mountApp('ready', '/preview/s1')
    expect(host.querySelector('.preview-window')).not.toBeNull()
    expect(host.querySelector('.nav-rail')).toBeNull()
  })

  it('has no preview window route in the web build', async () => {
    const { host, router } = await mountApp('ready', '/preview/s1')
    expect(router.currentRoute.value.name).toBe('workspace')
    expect(host.querySelector('.preview-window')).toBeNull()
  })

  it('takes the paths the desktop app was opened with', async () => {
    await mountApp('ready')
    expect(openPaths).toHaveBeenCalled()
  })
})

const overlay = () => document.querySelector('[data-overlay="reconnecting"]')

function desktop(shell: Partial<DesktopShell> = {}): DesktopShell {
  const full = {
    retryBackend: vi.fn<() => Promise<void>>(async () => {}),
    onQuitRequested: () => () => {},
    quitReady: async () => {},
    quit: vi.fn<() => Promise<void>>(async () => {}),
    hideMainWindow: vi.fn<() => Promise<void>>(async () => {}),
    settings: async () => ({ tray: false }),
    ...shell,
  } as Partial<DesktopShell> as DesktopShell
  platform.kind = 'desktop'
  platform.desktop = full
  return full
}

describe('the desktop app shell', () => {
  const ready = {
    state: 'ready',
    info: {
      baseUrl: 'http://127.0.0.1:8731',
      token: 't',
      instance: 'i',
      owned: true,
      privateQueue: null,
    },
  } as const

  it('shows why the server is not running, with its log and a Retry', async () => {
    const shell = desktop()
    desktopBackend.value = {
      state: 'failed',
      error: { message: 'No ready line within 20 s', log: '/d/logs/sidecar.log' },
    }
    const { host } = await mountApp('booting')
    expect(host.querySelector('h1')?.textContent).toBe('The Reframe server is not running')
    expect(host.querySelector('[data-field="message"]')?.textContent).toBe(
      'No ready line within 20 s',
    )
    expect(host.querySelector('[data-field="log"]')?.textContent).toBe('/d/logs/sidecar.log')
    expect(host.querySelector('.boot-screen')).toBeNull()
    const retry = host.querySelector<HTMLButtonElement>('[data-action="retry-backend"]')
    expect(document.activeElement).toBe(retry)
    retry?.click()
    await flushPromises()
    expect(shell.retryBackend).toHaveBeenCalledOnce()

    // The next start of the server replaces the screen.
    desktopBackend.value = { state: 'starting' }
    await flushPromises()
    expect(host.querySelector('[data-action="retry-backend"]')).toBeNull()
    expect(host.querySelector('.boot-screen')).not.toBeNull()
  })

  it('shows the error screen without a log when there is none', async () => {
    desktop()
    desktopBackend.value = { state: 'failed', error: { message: 'No server', log: null } }
    const { host } = await mountApp('booting')
    expect(host.querySelector('[data-field="message"]')?.textContent).toBe('No server')
    expect(host.querySelector('[data-field="log"]')).toBeNull()
  })

  it('shows Reconnecting… over the app and its dialogs, and gives the focus back after it', async () => {
    desktop()
    desktopBackend.value = ready
    const { host } = await mountApp('ready', '/queue')
    // What PrimeVue puts at the end of the page: a dialog, a select's list.
    const teleported = document.createElement('div')
    document.body.append(teleported)
    const link = host.querySelector<HTMLElement>('.nav-rail [aria-current="page"]')
    link?.focus()
    expect(overlay()).toBeNull()

    desktopBackend.value = { state: 'starting' }
    await flushPromises()
    expect(overlay()?.textContent).toContain('Reconnecting…')
    expect(host.hasAttribute('inert')).toBe(true)
    expect(teleported.hasAttribute('inert')).toBe(true)
    expect(overlay()?.closest('[inert]')).toBeNull()
    expect(overlay()?.contains(document.activeElement)).toBe(true)

    desktopBackend.value = ready
    await flushPromises()
    expect(overlay()).toBeNull()
    expect(host.hasAttribute('inert')).toBe(false)
    expect(teleported.hasAttribute('inert')).toBe(false)
    expect(document.activeElement).toBe(link)
  })

  it('shows Reconnecting… over the detached preview window too', async () => {
    vi.stubEnv('VITE_PLATFORM', 'desktop')
    desktop()
    desktopBackend.value = ready
    const { host } = await mountApp('ready', '/preview/s1')
    desktopBackend.value = { state: 'starting' }
    await flushPromises()
    expect(overlay()).not.toBeNull()
    expect(host.querySelector('.preview-window')?.closest('[inert]')).not.toBeNull()
  })

  it('shows the boot screen, not Reconnecting…, while the first start is tried again', async () => {
    desktop()
    desktopBackend.value = { state: 'starting' }
    const { host } = await mountApp('booting')
    expect(host.querySelector('.boot-screen')).not.toBeNull()
    expect(overlay()).toBeNull()
  })

  it('says above every view that a private queue is not saved and not shared', async () => {
    desktop()
    const detail = 'reframe-server 0.1.0 (pid 4242) owns the queue in web mode'
    desktopBackend.value = {
      state: 'ready',
      info: { ...ready.info, owned: true, privateQueue: { reason: 'webServer', detail } },
    }
    const { host, router } = await mountApp('ready')
    const banners = () => host.querySelectorAll('[data-component="private-queue-banner"]')
    async function visit(view: string): Promise<void> {
      await router.push({ name: view })
      await flushPromises()
      expect(banners()).toHaveLength(1)
    }
    await visit('queue')
    await visit('presets')
    await visit('activity')
    await visit('settings')
    await visit('workspace')
    const banner = banners()[0]
    expect(banner?.textContent).toContain('The queue of this window is not saved and not shared.')
    expect(banner?.querySelector('[data-field="reason"]')?.textContent).toBe(
      'A Reframe server in web mode owns the shared queue.',
    )
    expect(banner?.querySelector('[data-field="detail"]')?.textContent).toBe(detail)

    desktopBackend.value = {
      state: 'ready',
      info: { ...ready.info, privateQueue: { reason: 'lockHeld', detail: 'pid 77' } },
    }
    await flushPromises()
    expect(banners()[0]?.querySelector('[data-field="reason"]')?.textContent).toBe(
      'Another Reframe program holds the shared queue, and its server does not answer.',
    )
    desktopBackend.value = ready
    await flushPromises()
    expect(banners()).toHaveLength(0)
  })

  it('opens no server file browser', async () => {
    desktop()
    const { host } = await mountApp('ready')
    void browse({ mode: 'files', multiple: true })
    await flushPromises()
    expect(document.querySelector('.file-browser')).toBeNull()
    expect(host.querySelector('.workspace')).not.toBeNull()
  })

  async function askToQuit(tray: boolean) {
    app?.unmount()
    document.body.replaceChildren()
    const listeners: (() => void)[] = []
    const shell = desktop({
      onQuitRequested(cb) {
        listeners.push(cb)
        return () => {}
      },
      settings: async () => ({ tray }),
    })
    desktopBackend.value = ready
    await mountApp('ready')
    app?.runWithContext(() => {
      const queue = useQueueStore()
      queue.loaded = true
      queue.jobs = [{ id: 'a', state: 'running', progress: { percent: 10 } } as QueueJob]
    })
    for (const listener of listeners) listener()
    await flushPromises()
    const dialog = document.querySelector('[data-dialog="quit"]')
    return { shell, dialog }
  }

  it('asks before it quits while a job runs, without the tray when it is off', async () => {
    const { shell, dialog } = await askToQuit(false)
    expect(dialog?.textContent).toContain('1 job is running or paused.')
    expect(dialog?.querySelector('[data-action="quit-tray"]')).toBeNull()
    dialog?.querySelector<HTMLButtonElement>('[data-action="quit-stop"]')?.click()
    await flushPromises()
    expect(shell.quit).toHaveBeenCalledOnce()
  })

  it('offers the tray when it is on, and Cancel keeps the app', async () => {
    const { shell, dialog } = await askToQuit(true)
    dialog?.querySelector<HTMLButtonElement>('[data-action="quit-tray"]')?.click()
    await flushPromises()
    expect(shell.hideMainWindow).toHaveBeenCalledOnce()

    const again = await askToQuit(true)
    again.dialog?.querySelector<HTMLButtonElement>('[data-action="quit-cancel"]')?.click()
    await flushPromises()
    expect(again.shell.quit).not.toHaveBeenCalled()
    expect(again.shell.hideMainWindow).not.toHaveBeenCalled()
  })

  it('describes its question, and puts the focus on a control after Cancel', async () => {
    const { dialog } = await askToQuit(false)
    const described = document.getElementById(dialog?.getAttribute('aria-describedby') ?? '')
    expect(described?.textContent).toContain('1 job is running or paused.')
    dialog?.querySelector<HTMLButtonElement>('[data-action="quit-cancel"]')?.click()
    await vi.waitFor(() => expect(document.querySelector('[data-dialog="quit"]')).toBeNull())
    expect(document.activeElement).toBe(document.querySelector('.nav-rail [aria-current="page"]'))
  })
})
