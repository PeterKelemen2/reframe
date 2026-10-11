import { createDesktopPlatform } from './desktop'
import type { Platform } from './types'
import { createWebPlatform } from './web'

export type { Platform, PlatformKind } from './types'

// `vite.config.ts` checks that VITE_PLATFORM is `web` or `desktop`, and Vite replaces
// `import.meta.env.VITE_PLATFORM` with a string literal at build time. The condition is
// therefore constant, and the bundler drops the implementation that the build does not use:
// the web bundle never contains `desktop.ts` (and, from D-4 on, the Tauri plugins).
export const platform: Platform =
  import.meta.env.VITE_PLATFORM === 'desktop' ? createDesktopPlatform() : createWebPlatform()
