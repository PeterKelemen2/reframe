import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AppSettings } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import LanguagePicker from './LanguagePicker.vue'
import { languages } from './testing'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountPicker(props: Record<string, unknown> = {}, favourites: string[] = []) {
  const changes: (string | null)[] = []
  const { wrapper } = await mountShell(LanguagePicker, {
    props: {
      modelValue: null,
      label: 'Language',
      'onUpdate:modelValue': (value: string | null) => {
        changes.push(value)
        void wrapper.setProps({ modelValue: value })
      },
      ...props,
    },
    setup: () => {
      useSystemStore().languages = languages()
      useSettingsStore().settings = { languages: { favourites } } as unknown as AppSettings
    },
  })
  mounted.push(wrapper)
  return { wrapper, changes }
}

const $ = <T extends HTMLElement = HTMLElement>(selector: string) =>
  document.querySelector<T>(selector)
const trigger = () => $<HTMLButtonElement>('.language-picker__trigger')!
// A closed dialog stays in the DOM until its leave transition ends, which jsdom never runs.
const search = () =>
  [...document.querySelectorAll<HTMLInputElement>('[data-role="search"]')].at(-1) ?? null
const isOpen = () => trigger().getAttribute('aria-expanded') === 'true'
const optionTags = () =>
  [...document.querySelectorAll<HTMLElement>('[role="option"]')].map((o) => o.dataset.tag)
const activeTag = () => {
  const id = search()?.getAttribute('aria-activedescendant')
  return id ? document.getElementById(id)?.dataset.tag : undefined
}
const group = (name: string) =>
  [...document.querySelectorAll<HTMLElement>(`[data-group="${name}"] [role="option"]`)].map(
    (o) => o.dataset.tag,
  )

async function key(target: HTMLElement | null, name: string): Promise<void> {
  target?.dispatchEvent(
    new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true }),
  )
  await flushPromises()
}

async function type(text: string): Promise<void> {
  const input = search()!
  input.value = text
  input.dispatchEvent(new Event('input', { bubbles: true }))
  await flushPromises()
}

async function open(): Promise<void> {
  trigger().focus()
  trigger().click()
  await flushPromises()
}

describe('the language picker', () => {
  it('shows the chosen language with the codes it is written with', async () => {
    await mountPicker({ modelValue: 'ger' })
    expect(trigger().textContent?.replace(/\s+/g, ' ').trim()).toBe('German ger · de')
  })

  it('shows the ISO 639-2/T code for an MP4', async () => {
    await mountPicker({ modelValue: 'de', container: 'mp4' })
    expect(trigger().textContent).toContain('deu · de')
  })

  it('shows a tag it cannot name as it is', async () => {
    await mountPicker({ modelValue: 'yue' })
    expect(trigger().textContent?.trim()).toBe('yue')
  })

  it('shows each language as it will be written', async () => {
    await mountPicker()
    await open()
    await type('hun')
    const option = document.getElementById(search()!.getAttribute('aria-activedescendant')!)!
    expect(option.querySelector('.language-picker__written')?.textContent).toBe(
      'Hungarian · hun (ISO 639-2) · hu (BCP 47)',
    )
    expect(option.textContent).toContain('magyar')
  })

  it('works with the keyboard alone: open, type, arrows, Enter, and the focus comes back', async () => {
    const { changes } = await mountPicker()
    trigger().focus()
    await key(trigger(), 'ArrowDown')
    expect(document.activeElement).toBe(search())
    await type('portug')
    expect(activeTag()).toBe('pt')
    await key(search(), 'ArrowDown')
    await key(search(), 'ArrowDown')
    await key(search(), 'ArrowDown')
    expect(activeTag()).toBe('pt-PT')
    await key(search(), 'ArrowUp')
    expect(activeTag()).toBe('pt-BR')
    await key(search(), 'Enter')
    expect(changes).toEqual(['pt-BR'])
    expect(isOpen()).toBe(false)
    expect(document.activeElement).toBe(trigger())
  })

  it('starts the search with a letter typed on the closed control', async () => {
    await mountPicker()
    trigger().focus()
    await key(trigger(), 'm')
    expect(search()?.value).toBe('m')
  })

  it('closes on Escape without a change, and the Escape does not reach a dialog around it', async () => {
    const { changes } = await mountPicker({ modelValue: 'hu' })
    const outer = vi.fn<(event: KeyboardEvent) => void>()
    document.addEventListener('keydown', outer)
    await open()
    await type('Portuguese')
    await key(search(), 'Escape')
    document.removeEventListener('keydown', outer)
    expect(isOpen()).toBe(false)
    expect(changes).toEqual([])
    expect(outer).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(trigger())
  })

  it('opens on the chosen language', async () => {
    await mountPicker({ modelValue: 'fr' })
    await open()
    expect(activeTag()).toBe('fr')
  })

  it('lists the favourites of the settings first, and a new favourite at once', async () => {
    await mountPicker({}, ['pt-BR', 'hu'])
    await open()
    expect(group('favourites')).toEqual(['pt-BR', 'hu'])
    expect(optionTags().slice(0, 2)).toEqual(['pt-BR', 'hu'])
    await key(search(), 'Escape')
    useSettingsStore().settings = {
      languages: { favourites: ['de', 'pt-BR', 'hu'] },
    } as unknown as AppSettings
    await open()
    expect(optionTags().slice(0, 3)).toEqual(['de', 'pt-BR', 'hu'])
  })

  it('offers a typed tag whose base language is listed', async () => {
    const { changes } = await mountPicker()
    await open()
    await type('de-at')
    expect(optionTags()).toEqual(['de-AT'])
    await key(search(), 'Enter')
    expect(changes).toEqual(['de-AT'])
    expect(trigger().textContent).toContain('German (Austria)')
  })

  it('says when nothing matches, and Enter then chooses nothing', async () => {
    const { changes } = await mountPicker()
    await open()
    await type('en-XX')
    expect($('[data-state="empty"]')?.textContent).toContain('en-XX')
    await key(search(), 'Enter')
    expect(changes).toEqual([])
    expect(isOpen()).toBe(true)
  })

  it('offers None first when clearable, and it gives null', async () => {
    const { changes } = await mountPicker({ modelValue: 'hu', clearable: true, noneLabel: 'Keep' })
    await open()
    expect(document.querySelector('[role="option"]')?.textContent?.trim()).toBe('Keep')
    await key(search(), 'Home')
    await key(search(), 'PageUp')
    expect(activeTag()).toBe('')
    await key(search(), 'Enter')
    expect(changes).toEqual([null])
    expect(trigger().textContent?.trim()).toBe('Keep')
  })

  it('offers no None when not clearable', async () => {
    await mountPicker({ modelValue: 'hu' })
    await open()
    expect(optionTags()).not.toContain('')
  })

  it('chooses an option with a click', async () => {
    const { changes } = await mountPicker()
    await open()
    $('[role="option"][data-tag="es-419"]')?.click()
    await flushPromises()
    expect(changes).toEqual(['es-419'])
  })

  it('hides the excluded languages', async () => {
    await mountPicker({ exclude: ['hun', 'en'] })
    await open()
    expect(optionTags()).not.toContain('hu')
    expect(optionTags()).not.toContain('en')
    expect(optionTags()).toContain('de')
  })

  it('does not open when disabled', async () => {
    await mountPicker({ disabled: true })
    trigger().click()
    await key(trigger(), 'ArrowDown')
    expect(isOpen()).toBe(false)
  })

  it('is named by its label and its value', async () => {
    await mountPicker({ modelValue: 'hu', labelledby: 'outer-label' })
    const ids = trigger().getAttribute('aria-labelledby')?.split(' ')
    expect(ids?.[0]).toBe('outer-label')
    expect(document.getElementById(ids![1]!)?.textContent).toContain('Hungarian')
  })
})
