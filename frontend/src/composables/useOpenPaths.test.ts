import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, effectScope } from 'vue'
import { createMemoryHistory } from 'vue-router'

import { platform } from '@/platform'
import type { DesktopShell } from '@/platform/types'
import { createAppRouter } from '@/router'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

import { useOpenPaths } from './useOpenPaths'

let handOver: ((paths: string[]) => void) | null
let scope = effectScope()

async function start() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory())
  await router.push('/queue')
  const app = createApp({}).use(pinia).use(router)
  const sources = useSourcesStore()
  vi.spyOn(sources, 'open').mockResolvedValue([])
  app.runWithContext(() => scope.run(() => useOpenPaths()))
  return { sources, system: useSystemStore(), router }
}

beforeEach(() => {
  handOver = null
  platform.desktop = {
    onOpenPaths(cb) {
      handOver = cb
      return () => (handOver = null)
    },
  } as Partial<DesktopShell> as DesktopShell
  scope = effectScope()
})

afterEach(() => {
  scope.stop()
  platform.desktop = null
  vi.restoreAllMocks()
})

describe('the paths the desktop app is opened with', () => {
  it('waits until the app is ready, then opens them once, files and folders together', async () => {
    const { sources, system } = await start()
    handOver?.(['/m/file1.mkv', '/m/folder'])
    await flushPromises()
    expect(sources.open).not.toHaveBeenCalled()
    system.phase = 'ready'
    await flushPromises()
    system.phase = 'offline'
    await flushPromises()
    system.phase = 'ready'
    await flushPromises()
    expect(sources.open).toHaveBeenCalledExactlyOnceWith(['/m/file1.mkv', '/m/folder'], {
      select: false,
    })
  })

  it('opens a second launch’s paths at once in the workspace', async () => {
    const { sources, system, router } = await start()
    expect(router.currentRoute.value.name).toBe('queue')
    system.phase = 'ready'
    await flushPromises()
    handOver?.(['/m/other.mkv'])
    await flushPromises()
    expect(sources.open).toHaveBeenCalledExactlyOnceWith(['/m/other.mkv'], { select: false })
    expect(router.currentRoute.value.name).toBe('workspace')
  })

  it('shows the first opened file, also when another one was shown', async () => {
    const { sources, system } = await start()
    sources.activeId = 'old'
    vi.mocked(sources.open).mockResolvedValue([
      { id: 'new1', path: '/m/new1.mkv', source: null },
      { id: 'new2', path: '/m/new2.mkv', source: null },
    ])
    const select = vi.spyOn(sources, 'select').mockResolvedValue()
    system.phase = 'ready'
    handOver?.(['/m/season'])
    await flushPromises()
    expect(select).toHaveBeenCalledExactlyOnceWith('new1')
  })

  it('stops listening with its scope', async () => {
    await start()
    expect(handOver).not.toBeNull()
    scope.stop()
    expect(handOver).toBeNull()
  })
})
