import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter, RouterLink, RouterView } from 'vue-router'

import { refocusAfterNavigation } from './focus'

/** The workspace's control that leads away, and two other views, each with its heading. */
const Workspace = defineComponent(
  () => () =>
    h('main', { class: 'workspace' }, [
      h('button', { class: 'workspace__open' }, 'Open files…'),
      h(RouterLink, { to: '/queue', class: 'to-queue' }, () => 'Queue'),
    ]),
)
const view = (name: string) =>
  defineComponent(
    () => () =>
      h('main', { 'data-view': name }, [
        h('h1', name),
        h(RouterLink, { to: '/', class: 'to-workspace' }, () => 'Back'),
      ]),
  )

async function mountApp(start: string) {
  const history = createMemoryHistory()
  history.replace(start)
  const router = createRouter({
    history,
    routes: [
      { path: '/', name: 'workspace', component: Workspace },
      { path: '/queue', name: 'queue', component: view('queue') },
      { path: '/presets', name: 'presets', component: view('presets') },
    ],
  })
  const remove = refocusAfterNavigation(router)
  // The router's first navigation starts as it is installed, with the page on screen.
  const wrapper = mount(
    defineComponent(() => () => h('nav', [h(RouterView)])),
    {
      attachTo: document.body,
      global: { plugins: [router] },
    },
  )
  await router.isReady()
  await flushPromises()
  return { router, wrapper, remove }
}

const cleanups: (() => void)[] = []

afterEach(() => {
  for (const cleanup of cleanups.splice(0)) cleanup()
  document.body.replaceChildren()
})

describe('refocusAfterNavigation', () => {
  it("puts the focus on the new view's heading when the old view took it away", async () => {
    const { wrapper, remove } = await mountApp('/')
    cleanups.push(remove, () => wrapper.unmount())
    const link = document.querySelector<HTMLElement>('.to-queue') as HTMLElement
    link.focus()
    link.click()
    await flushPromises()
    expect(document.activeElement?.tagName).toBe('H1')
    expect(document.activeElement?.textContent).toBe('queue')
  })

  it('puts the focus on the workspace when another view leads back to it', async () => {
    const { wrapper, remove } = await mountApp('/queue')
    cleanups.push(remove, () => wrapper.unmount())
    const link = document.querySelector<HTMLElement>('.to-workspace') as HTMLElement
    link.focus()
    link.click()
    await flushPromises()
    expect(document.activeElement?.className).toBe('workspace__open')
  })

  it('leaves a focus that stays on screen, and takes none on the first view', async () => {
    const { router, wrapper, remove } = await mountApp('/')
    cleanups.push(remove, () => wrapper.unmount())
    expect(document.activeElement).toBe(document.body)
    const kept = document.createElement('button')
    document.body.append(kept)
    kept.focus()
    await router.push('/presets')
    await flushPromises()
    expect(document.activeElement).toBe(kept)
  })
})
