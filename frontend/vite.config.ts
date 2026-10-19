import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

const PLATFORMS = ['web', 'desktop'] as const

// The local reframe-server on its default port. The dev server forwards REST calls and the
// `/api/events` WebSocket to it, so the browser sees one origin (CORS stays off in web mode).
const BACKEND = 'http://127.0.0.1:8765'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), 'VITE_')
  const platform = env.VITE_PLATFORM ?? 'web'
  if (!(PLATFORMS as readonly string[]).includes(platform)) {
    throw new Error(`VITE_PLATFORM must be one of ${PLATFORMS.join(', ')}, got "${platform}"`)
  }

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    define: {
      // vue-i18n compile-time feature flags (Composition API only, no devtools in production).
      __VUE_I18N_FULL_INSTALL__: true,
      __VUE_I18N_LEGACY_API__: false,
      __INTLIFY_PROD_DEVTOOLS__: false,
    },
    server: {
      host: '127.0.0.1',
      proxy: {
        '/api': {
          target: BACKEND,
          ws: true,
        },
      },
    },
    build: {
      target: 'es2023',
    },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.ts'],
    },
  }
})
