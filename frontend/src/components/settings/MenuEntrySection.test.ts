import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { mountShell } from '@/components/shell/testing'
import type { DesktopMenuEntry, DesktopShell } from '@/platform/types'

import MenuEntrySection from './MenuEntrySection.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

/** The shell's menu entry; `refuse` makes the next change fail with that reason. */
function fakeShell(entry: DesktopMenuEntry) {
  const state = { entry, sent: [] as boolean[], refuse: null as string | null }
  const shell = {
    menuEntry: async () => state.entry,
    async setMenuEntry(add: boolean) {
      state.sent.push(add)
      if (state.refuse !== null) throw state.refuse
      state.entry = { ...state.entry, added: add }
      return state.entry
    },
  } as Partial<DesktopShell> as DesktopShell
  return { shell, state }
}

async function mountSection(entry: Partial<DesktopMenuEntry> = {}) {
  const initial = { appimage: '/a/Reframe.AppImage', added: false, other: null, ...entry }
  const { shell, state } = fakeShell(initial)
  const { wrapper } = await mountShell(MenuEntrySection, { props: { shell, entry: initial } })
  mounted.push(wrapper as VueWrapper)
  await flushPromises()
  const toggle = () => wrapper.find<HTMLInputElement>('[data-field="menu-entry"] input')
  return { wrapper, state, toggle }
}

describe('the Settings control of the AppImage’s menu entry', () => {
  it('adds the entry and removes it again', async () => {
    const { state, toggle } = await mountSection()
    expect(toggle().element.checked).toBe(false)
    await toggle().setValue(true)
    await flushPromises()
    expect(toggle().element.checked).toBe(true)
    await toggle().setValue(false)
    await flushPromises()
    expect(state.sent).toEqual([true, false])
    expect(toggle().element.checked).toBe(false)
  })

  it('shows the real state and the reason when the shell refuses', async () => {
    const { wrapper, state, toggle } = await mountSection({ added: true })
    state.refuse = 'Permission denied (os error 13)'
    await toggle().setValue(false)
    await flushPromises()
    expect(toggle().element.checked).toBe(true)
    expect(wrapper.text()).toContain('Permission denied (os error 13)')
  })

  it('names another entry instead of offering one', async () => {
    const { wrapper, toggle } = await mountSection({
      other: '/usr/share/applications/Reframe.desktop',
    })
    expect(toggle().exists()).toBe(false)
    expect(wrapper.find('[data-field="menu-entry-other"]').text()).toContain(
      '/usr/share/applications/Reframe.desktop',
    )
  })
})
