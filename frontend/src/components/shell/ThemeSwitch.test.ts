import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountShell } from './testing'
import ThemeSwitch from './ThemeSwitch.vue'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

describe('the theme switch', () => {
  it('takes the focus into its panel when it opens, and gives it back on Escape', async () => {
    const { wrapper } = await mountShell(ThemeSwitch)
    mounted.push(wrapper)
    const trigger = wrapper.find<HTMLButtonElement>('.theme-switch__button').element
    trigger.focus()
    trigger.click()
    await flushPromises()
    const panel = document.querySelector('.theme-switch')
    await vi.waitFor(() => expect(panel?.contains(document.activeElement)).toBe(true))
    expect(document.activeElement?.textContent?.trim()).toBe('System')

    document.activeElement?.dispatchEvent(
      new KeyboardEvent('keydown', { code: 'Escape', key: 'Escape', bubbles: true }),
    )
    await flushPromises()
    expect(document.activeElement).toBe(trigger)
  })
})
