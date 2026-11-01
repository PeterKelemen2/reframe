import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useUiStore } from '@/stores/ui'

import EditorTabs from './EditorTabs.vue'
import { mountShell } from './testing'

vi.mock('@/components/editor/tabs/registry', () => {
  const stand = { template: '<p>tab</p>' }
  const tab = (id: string, shortcut: number) => ({
    id,
    labelKey: `app.tabs.${id}`,
    shortcut,
    component: () => Promise.resolve(stand),
  })
  return { EDITOR_TABS: [tab('summary', 1), tab('video', 4), tab('audio', 5)] }
})

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

describe('the editor tabs', () => {
  it('open at the top of their panel, whatever the previous tab was scrolled to', async () => {
    const { wrapper, pinia } = await mountShell(EditorTabs)
    mounted.push(wrapper)
    const panels = wrapper.find('.editor-tabs__panels').element
    // jsdom does not scroll: its scrollTop is read only.
    let top = 300
    Object.defineProperty(panels, 'scrollTop', {
      get: () => top,
      set: (value: number) => {
        top = value
      },
      configurable: true,
    })

    useUiStore(pinia).activeTab = 'audio'
    await flushPromises()

    expect(top).toBe(0)
  })
})
