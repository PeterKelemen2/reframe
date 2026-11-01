import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { type App as VueApp, createApp } from 'vue'
import { createMemoryHistory } from 'vue-router'

import type { QueueJob } from '@/api/types'
import App from '@/App.vue'
import { platform } from '@/platform'
import { createAppRouter } from '@/router'
import { installPlugins } from '@/setup'
import { type AppPhase, useSystemStore } from '@/stores/system'
import { useQueueStore } from '@/stores/queue'

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

afterEach(() => {
  app?.unmount()
  app = undefined
  document.body.replaceChildren()
  vi.restoreAllMocks()
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
})
