import { flushPromises } from '@vue/test-utils'
import Listbox from 'primevue/listbox'
import { afterEach, describe, expect, it } from 'vitest'
import { type App, createApp, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

import { installPlugins } from '@/setup'

let app: App | undefined

/** Mounts `render` with the app's plugins, as `main.ts` installs them. */
async function mountApp(render: () => ReturnType<typeof h>): Promise<HTMLElement> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { render: () => null } }],
  })
  const root = document.createElement('div')
  document.body.append(root)
  app = installPlugins(createApp({ render }), router)
  app.mount(root)
  await flushPromises()
  return root
}

afterEach(() => {
  app?.unmount()
  app = undefined
  document.body.replaceChildren()
})

describe("PrimeVue's own texts", () => {
  it('come from the messages, and a count reads right when it is 1', async () => {
    const root = await mountApp(() =>
      h('div', [
        h(Listbox, { options: ['MKV', 'MP4'], modelValue: 'MKV', class: 'chosen' }),
        h(Listbox, { options: [], class: 'empty' }),
      ]),
    )
    const live = [...root.querySelectorAll('.chosen [aria-live]')].map((n) => n.textContent)
    expect(live).toContain('Options selected: 1')
    expect(root.querySelector('.empty')?.textContent).toContain('No options')
    expect(root.querySelector('.empty')?.textContent).toContain('Nothing selected')
  })
})
