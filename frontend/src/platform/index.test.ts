import { afterEach, describe, expect, it, vi } from 'vitest'

async function loadPlatform() {
  vi.resetModules()
  const { platform } = await import('./index')
  return platform
}

describe('platform selector', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('picks the web implementation by default (.env)', async () => {
    expect(import.meta.env.VITE_PLATFORM).toBe('web')
    const platform = await loadPlatform()
    expect(platform.kind).toBe('web')
    expect(platform.revealInFolder('/tmp/x')).toBeNull()
    await expect(platform.backend()).resolves.toEqual({ baseUrl: window.location.origin })
  })

  it('picks the desktop stub when VITE_PLATFORM=desktop', async () => {
    vi.stubEnv('VITE_PLATFORM', 'desktop')
    const platform = await loadPlatform()
    expect(platform.kind).toBe('desktop')
    await expect(platform.backend()).rejects.toThrow('not available in this build yet')
  })
})

describe('web platform', () => {
  it('shows taskbar progress in the document title', async () => {
    document.title = 'Reframe'
    const platform = await loadPlatform()
    platform.setTaskbarProgress(0.423)
    expect(document.title).toBe('42% · Reframe')
    platform.setTaskbarProgress(null)
    expect(document.title).toBe('Reframe')
  })

  it('opens the file browser for files and gives its choice, or nothing when cancelled', async () => {
    const platform = await loadPlatform()
    const { currentRequest, finish } = await import('@/components/sources/fileBrowser')
    const picked = platform.pickFiles({ multiple: true, filters: ['.MKV', 'mp4'] })
    const request = currentRequest()
    expect(request).toMatchObject({ mode: 'files', multiple: true, filters: ['mkv', 'mp4'] })
    finish(request!, ['/m/a.mkv', '/m/b.mkv'])
    expect(await picked).toEqual(['/m/a.mkv', '/m/b.mkv'])
    expect(currentRequest()).toBeNull()

    const cancelled = platform.pickFiles({ multiple: false })
    finish(currentRequest()!, null)
    expect(await cancelled).toEqual([])
  })

  it('opens the file browser for a folder and for a path to save', async () => {
    const platform = await loadPlatform()
    const { currentRequest, finish } = await import('@/components/sources/fileBrowser')
    const folder = platform.pickFolder({ title: 'Output folder' })
    expect(currentRequest()).toMatchObject({ mode: 'folder', title: 'Output folder' })
    finish(currentRequest()!, ['/srv/out'])
    expect(await folder).toBe('/srv/out')

    const save = platform.pickSavePath({ defaultPath: '/srv/out/a.mkv' })
    expect(currentRequest()).toMatchObject({ mode: 'save', defaultPath: '/srv/out/a.mkv' })
    finish(currentRequest()!, null)
    expect(await save).toBeNull()
  })

  it('cancels an open picker when another one opens', async () => {
    const platform = await loadPlatform()
    const { currentRequest, finish } = await import('@/components/sources/fileBrowser')
    const first = platform.pickFiles({ multiple: true })
    const stale = currentRequest()!
    const second = platform.pickFolder()
    expect(await first).toEqual([])
    finish(stale, ['/m/late.mkv'])
    expect(currentRequest()).toMatchObject({ mode: 'folder' })
    finish(currentRequest()!, ['/m'])
    expect(await second).toBe('/m')
  })
})
