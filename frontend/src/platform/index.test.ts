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
    await expect(platform.backend()).rejects.toThrow('not implemented (D-4)')
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
})
