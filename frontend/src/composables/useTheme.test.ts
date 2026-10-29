import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive, watch } from 'vue'

import type { AppSettings } from '@/api/types'
import { DARK_MODE_CLASS } from '@/styles/theme'

// A test double of the settings store: `settings` as Pinia unwraps it, and `set`.
const settingsStore = reactive({
  settings: null as AppSettings | null,
  set: vi.fn<(pointer: string, value: unknown) => Promise<unknown>>(),
})
vi.mock('@/stores/settings', () => ({ useSettingsStore: () => settingsStore }))

const KEY = 'reframe.appearance'

/** A `prefers-color-scheme: dark` query whose answer the test changes. */
function fakeSystemScheme(dark: boolean) {
  const listeners = new Set<() => void>()
  const query = {
    matches: dark,
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
  }
  window.matchMedia = vi.fn<(q: string) => MediaQueryList>(() => query as unknown as MediaQueryList)
  return (next: boolean) => {
    query.matches = next
    for (const listener of listeners) listener()
  }
}

const added: [string, EventListenerOrEventListenerObject][] = []

/** The module keeps its state, as the page does: each test loads it anew, as a reload does. */
async function load() {
  vi.resetModules()
  return import('./useTheme')
}

function html() {
  return document.documentElement
}

function appearance(theme: string, density: string): AppSettings {
  return { appearance: { theme, density, ui_language: 'en' } } as AppSettings
}

beforeEach(() => {
  localStorage.clear()
  html().className = ''
  html().removeAttribute('data-density')
  settingsStore.settings = null
  settingsStore.set.mockReset()
  settingsStore.set.mockResolvedValue({})
  const original = window.addEventListener.bind(window)
  vi.spyOn(window, 'addEventListener').mockImplementation((type, listener, options) => {
    if (listener) added.push([type, listener])
    original(type, listener, options)
  })
})

afterEach(() => {
  for (const [type, listener] of added.splice(0)) window.removeEventListener(type, listener)
  vi.restoreAllMocks()
})

describe('initTheme', () => {
  it('applies the stored theme and density before the app mounts', async () => {
    fakeSystemScheme(false)
    localStorage.setItem(KEY, JSON.stringify({ theme: 'dark', density: 'compact' }))
    const { initTheme } = await load()
    initTheme()
    expect(html().classList.contains(DARK_MODE_CLASS)).toBe(true)
    expect(html().dataset.density).toBe('compact')
  })

  it('follows the system scheme without a stored choice, and while it changes', async () => {
    const setSystemDark = fakeSystemScheme(true)
    const { initTheme, useTheme } = await load()
    initTheme()
    expect(html().classList.contains(DARK_MODE_CLASS)).toBe(true)
    expect(html().dataset.density).toBe('comfortable')
    setSystemDark(false)
    expect(html().classList.contains(DARK_MODE_CLASS)).toBe(false)
    expect(useTheme().dark.value).toBe(false)
  })

  it('ignores a stored value it does not know, and storage that throws', async () => {
    fakeSystemScheme(false)
    localStorage.setItem(KEY, JSON.stringify({ theme: 'purple', density: 'compact' }))
    let { initTheme, useTheme } = await load()
    initTheme()
    expect(useTheme().theme.value).toBe('system')
    expect(html().dataset.density).toBe('compact')

    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    ;({ initTheme, useTheme } = await load())
    initTheme()
    useTheme().setTheme('dark')
    expect(html().classList.contains(DARK_MODE_CLASS)).toBe(true)
  })
})

describe('useTheme', () => {
  it('switches theme and density at once and keeps them after a reload', async () => {
    fakeSystemScheme(false)
    let { useTheme } = await load()
    const theme = useTheme()
    theme.setTheme('dark')
    expect(html().classList.contains(DARK_MODE_CLASS)).toBe(true)
    theme.setDensity('compact')
    expect(html().dataset.density).toBe('compact')
    theme.setTheme('light')
    expect(html().classList.contains(DARK_MODE_CLASS)).toBe(false)

    html().className = ''
    html().removeAttribute('data-density')
    ;({ useTheme } = await load())
    const reloaded = useTheme()
    expect(reloaded.theme.value).toBe('light')
    expect(reloaded.density.value).toBe('compact')
    expect(html().dataset.density).toBe('compact')
  })

  it('writes the choice to the settings only once they have loaded', async () => {
    fakeSystemScheme(false)
    const { useTheme } = await load()
    const theme = useTheme()
    theme.setTheme('dark')
    expect(settingsStore.set).not.toHaveBeenCalled()

    settingsStore.settings = appearance('dark', 'comfortable')
    theme.setTheme('light')
    theme.setDensity('compact')
    expect(settingsStore.set.mock.calls).toEqual([
      ['/appearance/theme', 'light'],
      ['/appearance/density', 'compact'],
    ])
  })

  it('takes a settings value that loads later over the local choice', async () => {
    fakeSystemScheme(false)
    localStorage.setItem(KEY, JSON.stringify({ theme: 'dark', density: 'compact' }))
    const { useTheme } = await load()
    const theme = useTheme()
    expect(theme.theme.value).toBe('dark')

    settingsStore.settings = appearance('light', 'comfortable')
    await vi.waitFor(() => expect(theme.theme.value).toBe('light'))
    expect(html().classList.contains(DARK_MODE_CLASS)).toBe(false)
    expect(html().dataset.density).toBe('comfortable')
    expect(JSON.parse(localStorage.getItem(KEY) ?? '{}')).toEqual({
      theme: 'light',
      density: 'comfortable',
    })
    expect(settingsStore.set).not.toHaveBeenCalled()
  })

  it('follows a settings change made elsewhere', async () => {
    fakeSystemScheme(false)
    settingsStore.settings = appearance('light', 'comfortable')
    const { useTheme } = await load()
    const theme = useTheme()
    settingsStore.settings = appearance('dark', 'comfortable')
    await vi.waitFor(() => expect(html().classList.contains(DARK_MODE_CLASS)).toBe(true))
    expect(theme.theme.value).toBe('dark')
  })

  it('never shows an older choice while its own writes are answered', async () => {
    fakeSystemScheme(false)
    settingsStore.settings = appearance('light', 'comfortable')
    const answers: (() => void)[] = []
    settingsStore.set.mockImplementation(
      (_pointer, value) =>
        new Promise((resolve) => {
          answers.push(() => {
            settingsStore.settings = appearance(value as string, 'comfortable')
            resolve({})
          })
        }),
    )
    const { useTheme } = await load()
    const theme = useTheme()
    const seen: boolean[] = []
    watch(theme.dark, (dark) => seen.push(dark), { flush: 'sync' })

    theme.setTheme('dark')
    theme.setTheme('system')
    answers[0]?.()
    await new Promise((resolve) => setTimeout(resolve))
    answers[1]?.()
    await new Promise((resolve) => setTimeout(resolve))

    expect(theme.theme.value).toBe('system')
    // dark, then light (system) once: the answer "dark" in between changed nothing.
    expect(seen).toEqual([true, false])
  })

  it('keeps the choice in this browser when the settings write fails', async () => {
    fakeSystemScheme(false)
    settingsStore.settings = appearance('light', 'comfortable')
    settingsStore.set.mockRejectedValue(new Error('offline'))
    const { useTheme } = await load()
    const theme = useTheme()
    theme.setTheme('dark')
    await new Promise((resolve) => setTimeout(resolve))
    expect(theme.theme.value).toBe('dark')
    expect(html().classList.contains(DARK_MODE_CLASS)).toBe(true)
  })

  it("follows another tab's choice", async () => {
    fakeSystemScheme(false)
    const { useTheme } = await load()
    const theme = useTheme()
    const newValue = JSON.stringify({ theme: 'dark', density: 'compact' })
    window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue }))
    expect(theme.theme.value).toBe('dark')
    expect(html().classList.contains(DARK_MODE_CLASS)).toBe(true)
    expect(html().dataset.density).toBe('compact')
  })
})
