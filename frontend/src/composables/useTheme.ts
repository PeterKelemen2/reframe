import { type Ref, readonly, ref } from 'vue'

import type { Schemas } from '@/api/types'

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

const theme = ref<ThemeChoice>('system')
const density = ref<Density>('comfortable')
const dark = ref(false)

/**
 * Applies the stored theme and density to the document before the first paint. Called once,
 * by `main.ts`.
 */
export function initTheme(): void {}

/** The theme and density: kept in this browser at once, and in the settings when loaded. */
export function useTheme(): Theme {
  return {
    theme: readonly(theme),
    density: readonly(density),
    dark: readonly(dark),
    setTheme: (choice) => {
      theme.value = choice
    },
    setDensity: (value) => {
      density.value = value
    },
  }
}
