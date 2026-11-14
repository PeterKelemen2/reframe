import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

const PLATFORMS = ['web', 'desktop'] as const

// The dev server forwards REST calls and the `/api/events` WebSocket to a reframe-server, so the
// browser sees one origin (CORS stays off in web mode). Default: the server's default port.
// Parallel checks each run their own server and dev server: REFRAME_DEV_BACKEND and
// REFRAME_DEV_PORT pick them. The dev server never opens a browser itself.
const BACKEND = process.env.REFRAME_DEV_BACKEND ?? 'http://127.0.0.1:8765'
const DEV_PORT = process.env.REFRAME_DEV_PORT ? Number(process.env.REFRAME_DEV_PORT) : undefined
// scripts/stamp-version.py writes the core's version here.
const VERSION = (
  JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as {
    version: string
  }
).version

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
      __REFRAME_VERSION__: JSON.stringify(VERSION),
    },
    server: {
      host: '127.0.0.1',
      port: DEV_PORT,
      strictPort: DEV_PORT !== undefined,
      proxy: {
        '/api': {
          target: BACKEND,
          ws: true,
        },
      },
    },
    build: {
      target: 'es2023',
      // The Tauri shell bundles its own build; the server serves `dist`.
      outDir: platform === 'desktop' ? 'dist-desktop' : 'dist',
    },
    test: {
      projects: [
        {
          extends: true,
          test: {
            name: 'unit',
            environment: 'jsdom',
            setupFiles: ['src/testing/setup.ts'],
            include: ['src/**/*.test.ts'],
            exclude: ['src/**/*.server.test.ts'],
          },
        },
        {
          // Against a real reframe-server (scripts/dev-server.py), so it needs `uv sync`: kept
          // out of `npm test`, which runs where only Node is installed.
          extends: true,
          test: {
            name: 'server',
            environment: 'node',
            include: ['src/**/*.server.test.ts'],
            fileParallelism: false,
            testTimeout: 60_000,
            hookTimeout: 60_000,
          },
        },
      ],
    },
  }
})
