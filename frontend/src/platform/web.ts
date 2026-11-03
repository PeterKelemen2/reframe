import { browse } from '@/components/sources/fileBrowser'

import type { Platform } from './types'

/** Browser implementation. The server serves the UI, so the backend is the page's origin. */
export function createWebPlatform(): Platform {
  let baseTitle: string | null = null

  return {
    kind: 'web',

    backend() {
      return Promise.resolve({ baseUrl: window.location.origin })
    },

    async pickFiles({ multiple, filters }) {
      return (await browse({ mode: 'files', multiple, filters })) ?? []
    },

    async pickFolder(options) {
      const chosen = await browse({ mode: 'folder', title: options?.title })
      return chosen?.[0] ?? null
    },

    async pickSavePath({ defaultPath }) {
      const chosen = await browse({ mode: 'save', defaultPath })
      return chosen?.[0] ?? null
    },

    onFilesDropped() {
      // Browsers do not expose real file paths on drop.
      return () => {}
    },

    revealInFolder() {
      return null
    },

    openExternal(target) {
      window.open(target, '_blank', 'noopener,noreferrer')
      return Promise.resolve()
    },

    async notify(title, body) {
      if (typeof Notification === 'undefined') return
      const permission =
        Notification.permission === 'default'
          ? await Notification.requestPermission()
          : Notification.permission
      if (permission !== 'granted') return
      const notification = new Notification(title, { body })
      notification.addEventListener('click', () => window.focus())
    },

    setTaskbarProgress(value) {
      baseTitle ??= document.title
      document.title =
        value === null
          ? baseTitle
          : `${Math.round(Math.min(Math.max(value, 0), 1) * 100)}% · ${baseTitle}`
    },

    desktop: null,
  }
}
