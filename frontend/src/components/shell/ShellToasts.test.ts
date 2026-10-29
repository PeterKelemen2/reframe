import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { useToastStore } from '@/stores/toasts'

import ShellToasts from './ShellToasts.vue'
import { mountShell } from './testing'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountToasts(setup?: () => void) {
  const result = await mountShell(ShellToasts, { setup })
  mounted.push(result.wrapper)
  return result
}

function shown(): string[] {
  return [...document.querySelectorAll('.p-toast-message')].map((message) =>
    [...message.querySelectorAll('.p-toast-summary, .p-toast-detail')]
      .map((part) => part.textContent?.trim())
      .filter(Boolean)
      .join(' / '),
  )
}

describe('the toasts', () => {
  it('shows the toasts pushed before and after it mounts, once each', async () => {
    await mountToasts(() => {
      useToastStore().push({ severity: 'error', summary: 'Early', detail: 'from the boot' })
    })
    const toasts = useToastStore()
    toasts.push({ severity: 'success', summary: 'Later' })
    await flushPromises()
    toasts.push({ severity: 'info', summary: 'Third' })
    await flushPromises()
    expect(shown()).toEqual(['Early / from the boot', 'Later', 'Third'])
  })

  it('keeps a toast in the store while it is on screen, and removes it when it is closed', async () => {
    await mountToasts()
    const toasts = useToastStore()
    toasts.push({ severity: 'error', summary: 'Server unreachable' })
    toasts.push({ severity: 'warn', summary: 'Other' })
    await flushPromises()
    expect(toasts.items.map((toast) => toast.summary)).toEqual(['Server unreachable', 'Other'])

    document.querySelector<HTMLButtonElement>('.p-toast-message .p-toast-close-button')?.click()
    await flushPromises()
    expect(toasts.items.map((toast) => toast.summary)).toEqual(['Other'])
    expect(shown()).toEqual(['Other'])
  })
})
