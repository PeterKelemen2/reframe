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

const host = () => document.querySelector<HTMLElement>('.shell-toasts')!
const at = (x: number, y: number) => () => new DOMRect(x, y, 100, 40)

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

  it('shows the toasts at the bottom right, clear of the status bar', async () => {
    await mountToasts()
    useToastStore().push({ severity: 'success', summary: 'Added' })
    await flushPromises()
    expect(host().classList.contains('p-toast-bottom-right')).toBe(true)
    expect(host().style.bottom).toContain('var(--shell-status-bar-height, 0px)')
  })

  it('moves to the other end of the window while the focus is on something it covers', async () => {
    await mountToasts()
    useToastStore().push({ severity: 'success', summary: 'Added' })
    await flushPromises()
    // jsdom lays nothing out: the message lies where its end of the window puts it.
    document.querySelector<HTMLElement>('.p-toast-message')!.getBoundingClientRect = () =>
      host().classList.contains('p-toast-top-right') ? at(900, 10)() : at(900, 600)()
    const [clear, coveredBelow, coveredAbove] = [at(100, 100), at(950, 620), at(950, 20)].map(
      (box) => {
        const button = document.createElement('button')
        button.getBoundingClientRect = box
        document.body.append(button)
        return button
      },
    ) as [HTMLButtonElement, HTMLButtonElement, HTMLButtonElement]

    clear.focus()
    await flushPromises()
    expect(host().classList.contains('p-toast-bottom-right')).toBe(true)
    coveredBelow.focus()
    await flushPromises()
    expect(host().classList.contains('p-toast-top-right')).toBe(true)
    expect([host().style.top, host().style.bottom]).toEqual(['var(--rf-space-3)', 'auto'])
    expect(host().classList.contains('shell-toasts--aside')).toBe(false)
    coveredAbove.focus()
    await flushPromises()
    expect(host().classList.contains('p-toast-bottom-right')).toBe(true)
    expect(host().classList.contains('shell-toasts--aside')).toBe(false)
  })

  it('goes out of sight while the focus is on something it covers at both ends', async () => {
    await mountToasts()
    useToastStore().push({ severity: 'success', summary: 'Added' })
    await flushPromises()
    document.querySelector<HTMLElement>('.p-toast-message')!.getBoundingClientRect = () =>
      new DOMRect(900, 0, 100, 720)
    const covered = document.createElement('button')
    covered.getBoundingClientRect = () => new DOMRect(950, 300, 20, 20)
    const clear = document.createElement('button')
    clear.getBoundingClientRect = () => new DOMRect(100, 300, 20, 20)
    document.body.append(covered, clear)
    covered.focus()
    await flushPromises()
    expect(host().classList.contains('shell-toasts--aside')).toBe(true)
    clear.focus()
    await flushPromises()
    expect(host().classList.contains('shell-toasts--aside')).toBe(false)
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
