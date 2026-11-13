import { flushPromises } from '@vue/test-utils'
import Listbox from 'primevue/listbox'
import { afterEach, describe, expect, it } from 'vitest'
import { type App, createApp, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

import { createAppI18n } from '@/i18n'
import { installPlugins } from '@/setup'

import { primeVueLocale } from './primevueLocale'

const modules = import.meta.glob<string>('/node_modules/primevue/*/index.mjs', {
  query: '?raw',
  import: 'default',
  eager: true,
})
const sources = import.meta.glob<string>(['/src/**/*.vue', '/src/**/*.ts', '!/src/**/*.test.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
})

/**
 * Locale texts of PrimeVue components the app uses, but of features it does not: DataTable's
 * filter menu and row editing, and the Paginator.
 */
const UNUSED_FEATURES = new Set([
  'addRule',
  'apply',
  'clear',
  'filterConstraint',
  'filterOperator',
  'matchAll',
  'matchAny',
  'noFilter',
  'removeRule',
  'aria.cancelEdit',
  'aria.editRow',
  'aria.saveEdit',
  'aria.showFilterMenu',
  'aria.hideFilterMenu',
  'aria.jumpToPageInputLabel',
  'aria.pageLabel',
])

const IMPORT = /from ['"]primevue\/([a-z]+)['"]/g
const LOCALE = /\$primevue\.config\.locale\.((?:aria\.)?[A-Za-z]+)/g

/** The PrimeVue modules the app imports, with the ones they import. */
function usedModules(): Set<string> {
  const used = new Set<string>()
  const add = (name: string): void => {
    if (used.has(name)) return
    used.add(name)
    for (const [, dep] of (modules[`/node_modules/primevue/${name}/index.mjs`] ?? '').matchAll(
      IMPORT,
    )) {
      add(dep as string)
    }
  }
  for (const source of Object.values(sources)) {
    for (const [, name] of source.matchAll(IMPORT)) add(name as string)
  }
  return used
}

function flatten(value: object, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, inner]) =>
    typeof inner === 'object' && inner !== null
      ? flatten(inner, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  )
}

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

  it('every text a used component reads comes from the messages', () => {
    const used = usedModules()
    expect(used.size).toBeGreaterThan(10)
    const read = new Set<string>()
    for (const name of used) {
      const source = modules[`/node_modules/primevue/${name}/index.mjs`] ?? ''
      for (const [, key] of source.matchAll(LOCALE)) {
        // `locale.aria` alone is the group, read before one of its keys.
        if (key !== 'aria') read.add(key as string)
      }
    }
    expect(read.size).toBeGreaterThan(5)
    const set = new Set(flatten(primeVueLocale(createAppI18n().global.t)))
    const missing = [...read].filter((key) => !set.has(key) && !UNUSED_FEATURES.has(key))
    expect(missing.toSorted()).toEqual([])
  })
})
