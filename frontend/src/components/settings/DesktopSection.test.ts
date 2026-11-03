import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { mountShell } from '@/components/shell/testing'
import type { DesktopSettings, DesktopShell } from '@/platform/types'

import DesktopSection from './DesktopSection.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

/** The shell's `desktop.json`; `refuse` makes the next save fail with that reason. */
function fakeShell(saved: DesktopSettings) {
  const state = { saved, sent: [] as DesktopSettings[], refuse: null as string | null }
  const shell = {
    settings: async () => state.saved,
    async setSettings(next: DesktopSettings) {
      state.sent.push(next)
      if (state.refuse !== null) throw state.refuse
      state.saved = next
      return next
    },
  } as Partial<DesktopShell> as DesktopShell
  return { shell, state }
}

async function mountSection(saved: DesktopSettings) {
  const { shell, state } = fakeShell(saved)
  const { wrapper } = await mountShell(DesktopSection, { props: { shell } })
  mounted.push(wrapper as VueWrapper)
  await flushPromises()
  const toggle = () => wrapper.find<HTMLInputElement>('[data-field="tray"] input')
  return { wrapper, state, toggle }
}

describe('the desktop app’s settings', () => {
  it('shows the saved tray setting', async () => {
    const { toggle } = await mountSection({ tray: true })
    expect(toggle().element.checked).toBe(true)
  })

  it('switches the tray on and saves it in the shell', async () => {
    const { state, toggle } = await mountSection({ tray: false })
    await toggle().setValue(true)
    await flushPromises()
    expect(state.sent).toEqual([{ tray: true }])
    expect(toggle().element.checked).toBe(true)
  })

  it('keeps the switch where it was and says why when the shell refuses', async () => {
    const { wrapper, state, toggle } = await mountSection({ tray: false })
    state.refuse = 'The tray needs the library libayatana-appindicator3'
    await toggle().setValue(true)
    await flushPromises()
    expect(toggle().element.checked).toBe(false)
    expect(wrapper.text()).toContain('The tray needs the library libayatana-appindicator3')
  })
})
