import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { type App as VueApp, createApp } from 'vue'
import { createMemoryHistory } from 'vue-router'

import App from '@/App.vue'
import { createAppRouter } from '@/router'
import { installPlugins } from '@/setup'

let app: VueApp | undefined

// Mounts the real app with the same plugin setup as main.ts (memory history instead of the URL).
async function mountApp(path: string) {
  const router = createAppRouter(createMemoryHistory())
  const host = document.createElement('div')
  document.body.append(host)
  app = installPlugins(createApp(App), router)
  await router.push(path)
  await router.isReady()
  app.mount(host)
  await flushPromises()
  return { host, router }
}

afterEach(() => {
  app?.unmount()
  app = undefined
  document.body.replaceChildren()
})

describe('App', () => {
  it('mounts with router, Pinia, i18n and PrimeVue and shows the workspace placeholder', async () => {
    const { host, router } = await mountApp('/')
    expect(router.currentRoute.value.name).toBe('workspace')
    expect(host.querySelector('h1')?.textContent?.trim()).toBe('Workspace')
    expect(host.textContent).toContain('Sources, settings and preview will appear here.')
    // A PrimeVue component rendered in styled mode, and its theme CSS injected into <head>.
    expect(host.querySelector('.p-message')).not.toBeNull()
    expect(document.head.querySelector('style[data-primevue-style-id]')).not.toBeNull()
    expect(host.querySelector('main')?.dataset.platform).toBe('web')
  })

  it('redirects unknown paths to the workspace', async () => {
    const { router } = await mountApp('/no/such/page')
    expect(router.currentRoute.value.name).toBe('workspace')
  })
})
