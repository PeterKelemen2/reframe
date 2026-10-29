import { mount } from '@vue/test-utils'
import { createPinia, type Pinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import type { Component } from 'vue'

import { createAppI18n } from '@/i18n'

/** Mounts a base component with the app's i18n, a fresh Pinia and PrimeVue without its CSS (tests only). */
export function mountBase<C extends Component>(
  component: C,
  options: { props?: Record<string, unknown>; slots?: Record<string, unknown>; pinia?: Pinia } = {},
) {
  const pinia = options.pinia ?? createPinia()
  setActivePinia(pinia)
  return mount(component, {
    props: options.props,
    slots: options.slots,
    attachTo: document.body,
    global: { plugins: [pinia, createAppI18n(), [PrimeVue, { theme: 'none' }]] },
  } as never)
}
