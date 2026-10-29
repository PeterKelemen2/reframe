import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, type Pinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import Tooltip from 'primevue/tooltip'
import type { Component } from 'vue'
import { createMemoryHistory, type Router } from 'vue-router'

import { createAppI18n } from '@/i18n'
import { createAppRouter } from '@/router'

// jsdom has none; PrimeVue's popover and scrollable tabs watch sizes with one.
globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

/**
 * Mounts a shell component with the app's i18n, router (memory history), a fresh Pinia and
 * PrimeVue without its CSS (tests only). `setup` runs with the Pinia active, before the mount.
 */
export async function mountShell<C extends Component>(
  component: C,
  options: {
    path?: string
    pinia?: Pinia
    props?: Record<string, unknown>
    setup?: () => void
  } = {},
) {
  const pinia = options.pinia ?? createPinia()
  setActivePinia(pinia)
  options.setup?.()
  const router: Router = createAppRouter(createMemoryHistory())
  await router.push(options.path ?? '/')
  await router.isReady()
  const wrapper = mount(component, {
    props: options.props,
    attachTo: document.body,
    global: {
      plugins: [pinia, router, createAppI18n(), [PrimeVue, { theme: 'none' }], ToastService],
      directives: { tooltip: Tooltip },
      // PrimeVue's overlays announce that they opened or closed from their transition's hooks.
      stubs: { transition: false },
    },
  } as never)
  await flushPromises()
  return { wrapper, router, pinia }
}
