import { effectScope, type Ref, readonly, ref, watch } from 'vue'

import type { Schemas } from '@/api/types'
import { useSettingsStore } from '@/stores/settings'
import { DARK_MODE_CLASS, DENSITY_ATTRIBUTE } from '@/styles/theme'

export type ThemeChoice = Schemas['AppearanceSettings']['theme']
export type Density = Schemas['AppearanceSettings']['density']

export interface Theme {
  theme: Readonly<Ref<ThemeChoice>>
  density: Readonly<Ref<Density>>
  /** The colour scheme in effect (`system` follows the operating system). */
  dark: Readonly<Ref<boolean>>
  setTheme(choice: ThemeChoice): void
  setDensity(density: Density): void
}

interface Appearance {
  theme?: ThemeChoice
  density?: Density
}

/** The key in `localStorage`; also how another tab's change reaches this one. */
export const THEME_STORAGE_KEY = 'reframe.appearance'
const THEMES: readonly string[] = ['system', 'light', 'dark'] satisfies ThemeChoice[]
const DENSITIES: readonly string[] = ['comfortable', 'compact'] satisfies Density[]

const theme = ref<ThemeChoice>('system')
const density = ref<Density>('comfortable')
const dark = ref(false)
let systemDark: MediaQueryList | null = null
let initialised = false

/** Settings stores whose appearance this module follows (one per Pinia). */
const followed = new WeakSet<object>()
/** Our own settings writes in flight: an answer to an older one must not undo a newer choice. */
let pendingWrites = 0
let settingsMovedWhilePending = false

/** Keeps only values this version knows: a newer version may store more. */
function known(value: unknown): Appearance {
  if (typeof value !== 'object' || value === null) return {}
  const { theme: t, density: d } = value as Record<string, unknown>
  return {
    theme: typeof t === 'string' && THEMES.includes(t) ? (t as ThemeChoice) : undefined,
    density: typeof d === 'string' && DENSITIES.includes(d) ? (d as Density) : undefined,
  }
}

function parseStored(raw: string | null | undefined): Appearance {
  if (!raw) return {}
  try {
    return known(JSON.parse(raw))
  } catch {
    return {}
  }
}

function readLocal(): Appearance {
  try {
    return parseStored(localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    return {}
  }
}

function writeLocal(): void {
  try {
    localStorage.setItem(
      THEME_STORAGE_KEY,
      JSON.stringify({ theme: theme.value, density: density.value }),
    )
  } catch {
    // Storage is blocked or full: the choice holds for this page only.
  }
}

function apply(): void {
  dark.value =
    theme.value === 'dark' || (theme.value === 'system' && (systemDark?.matches ?? false))
  const root = document.documentElement
  root.classList.toggle(DARK_MODE_CLASS, dark.value)
  root.setAttribute(DENSITY_ATTRIBUTE, density.value)
}

function adopt(next: Appearance, persist: boolean): void {
  if (next.theme) theme.value = next.theme
  if (next.density) density.value = next.density
  apply()
  if (persist) writeLocal()
}

/**
 * Applies the stored theme and density to the document before the first paint. Called once,
 * by `main.ts`; later calls do nothing.
 */
export function initTheme(): void {
  if (initialised) return
  initialised = true
  if (typeof window.matchMedia === 'function') {
    systemDark = window.matchMedia('(prefers-color-scheme: dark)')
    systemDark.addEventListener('change', apply)
  }
  window.addEventListener('storage', (event) => {
    if (event.key === THEME_STORAGE_KEY) adopt(parseStored(event.newValue), false)
  })
  adopt(readLocal(), false)
}

type SettingsStore = ReturnType<typeof useSettingsStore>

function serverAppearance(store: SettingsStore): Appearance {
  return known(store.settings?.appearance)
}

/** A settings value that arrives (loaded, or changed elsewhere) wins over this browser's. */
function follow(store: SettingsStore): void {
  if (followed.has(store)) return
  followed.add(store)
  effectScope(true).run(() => {
    watch(
      () => [store.settings?.appearance?.theme, store.settings?.appearance?.density],
      () => {
        if (pendingWrites > 0) {
          settingsMovedWhilePending = true
          return
        }
        const next = serverAppearance(store)
        if (next.theme || next.density) adopt(next, true)
      },
      { immediate: true },
    )
  })
}

function save(store: SettingsStore, key: keyof Appearance, value: string): void {
  if (store.settings === null || serverAppearance(store)[key] === value) return
  pendingWrites += 1
  store
    .set(`/appearance/${key}`, value)
    .catch(() => {
      // The API layer reports the failure; the choice stays in this browser.
    })
    .finally(() => {
      pendingWrites -= 1
      if (pendingWrites > 0 || !settingsMovedWhilePending) return
      settingsMovedWhilePending = false
      adopt(serverAppearance(store), true)
    })
}

/** The theme and density: kept in this browser at once, and in the settings when loaded. */
export function useTheme(): Theme {
  initTheme()
  const store = useSettingsStore()
  follow(store)
  return {
    theme: readonly(theme),
    density: readonly(density),
    dark: readonly(dark),
    setTheme: (choice) => {
      adopt({ theme: choice }, true)
      save(store, 'theme', choice)
    },
    setDensity: (value) => {
      adopt({ density: value }, true)
      save(store, 'density', value)
    },
  }
}
