import { createDesktopPlatform } from './desktop'
import type { Platform } from './types'
import { createWebPlatform } from './web'

export type { Platform, PlatformKind } from './types'

// Vite inlines `import.meta.env.VITE_PLATFORM` as a literal, so the condition is constant and the
// bundler drops the unused implementation: the web bundle never contains `desktop.ts`.
export const platform: Platform =
  import.meta.env.VITE_PLATFORM === 'desktop' ? createDesktopPlatform() : createWebPlatform()
