import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { mountShell } from '@/components/shell/testing'
import { useSystemStore } from '@/stores/system'

import LanguageListEditor from './LanguageListEditor.vue'
import LanguagePicker from './LanguagePicker.vue'
import { languages } from './testing'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountList(modelValue: string[], props: Record<string, unknown> = {}) {
  const changes: string[][] = []
  const { wrapper } = await mountShell(LanguageListEditor, {
    props: {
      modelValue,
      label: 'Favourites',
      'onUpdate:modelValue': (value: string[]) => {
        changes.push(value)
        void wrapper.setProps({ modelValue: value })
      },
      ...props,
    },
    setup: () => {
      useSystemStore().languages = languages()
    },
  })
  mounted.push(wrapper)
  return { wrapper, changes }
}

const items = () => [...document.querySelectorAll<HTMLElement>('[data-role="item"]')]
const item = (tag: string) =>
  document.querySelector<HTMLElement>(`[data-role="item"][data-tag="${tag}"]`)!
const button = (tag: string, selector: string) =>
  item(tag).querySelector<HTMLButtonElement>(selector)!
const focused = () => {
  const active = document.activeElement as HTMLElement | null
  const owner = active?.closest<HTMLElement>('[data-role="item"]')
  return `${owner?.dataset.tag ?? ''} ${active?.dataset.move ?? active?.dataset.action ?? ''}`
}

async function click(target: HTMLElement): Promise<void> {
  target.focus()
  target.click()
  await flushPromises()
}

function drag(type: string, target: HTMLElement): void {
  const event = new Event(type, { bubbles: true, cancelable: true })
  target.dispatchEvent(event)
}

describe('the language list editor', () => {
  it('shows each language in order with the codes it is written with', async () => {
    await mountList(['hu', 'pt-BR', 'xx-unknown'])
    expect(
      items().map((li) => li.querySelector('.language-list__text')?.textContent?.trim()),
    ).toEqual(['Hungarian hun · hu', 'Portuguese (Brazil) por · pt-BR', 'xx-unknown'])
  })

  it('adds a language from the picker at the end, and the picker hides the ones listed', async () => {
    const { wrapper, changes } = await mountList(['hu'])
    const picker = wrapper.findComponent(LanguagePicker)
    expect(picker.props('exclude')).toEqual(['hu'])
    picker.vm.$emit('update:modelValue', 'de')
    await flushPromises()
    expect(changes).toEqual([['hu', 'de']])
  })

  it('adds no language twice', async () => {
    const { wrapper, changes } = await mountList(['hu'])
    wrapper.findComponent(LanguagePicker).vm.$emit('update:modelValue', 'hu')
    await flushPromises()
    expect(changes).toEqual([])
  })

  it('moves a language up and down, and the focus stays on the moved language', async () => {
    const { changes } = await mountList(['hu', 'en', 'de'])
    await click(button('de', '[data-move="up"]'))
    expect(changes.at(-1)).toEqual(['hu', 'de', 'en'])
    expect(focused()).toBe('de up')
    await click(button('de', '[data-move="up"]'))
    expect(changes.at(-1)).toEqual(['de', 'hu', 'en'])
    // At the top its up button is disabled: the focus goes to its down button.
    expect(focused()).toBe('de down')
    await click(button('hu', '[data-move="down"]'))
    expect(changes.at(-1)).toEqual(['de', 'en', 'hu'])
    expect(focused()).toBe('hu up')
  })

  it('removes a language; the focus goes to the next one, or to the add control', async () => {
    const { changes } = await mountList(['hu', 'en'])
    await click(button('hu', '[data-action="remove"]'))
    expect(changes.at(-1)).toEqual(['en'])
    expect(focused()).toBe('en remove')
    await click(button('en', '[data-action="remove"]'))
    expect(changes.at(-1)).toEqual([])
    expect(document.activeElement?.classList.contains('language-picker__trigger')).toBe(true)
    expect(document.querySelector('[data-state="empty"]')).not.toBeNull()
  })

  it('moves a dragged language to where it is dropped', async () => {
    const { changes } = await mountList(['hu', 'en', 'de'])
    drag('dragstart', item('de'))
    drag('dragover', item('hu'))
    await flushPromises()
    expect(item('hu').classList).toContain('language-list__item--drop-before')
    drag('drop', item('hu'))
    await flushPromises()
    expect(changes).toEqual([['de', 'hu', 'en']])
    drag('dragstart', item('de'))
    drag('dragover', item('en'))
    drag('drop', item('en'))
    await flushPromises()
    expect(changes.at(-1)).toEqual(['hu', 'en', 'de'])
  })

  it('takes no drop that did not start in the list', async () => {
    const { changes } = await mountList(['hu', 'en'])
    drag('dragover', item('hu'))
    drag('drop', item('hu'))
    await flushPromises()
    expect(changes).toEqual([])
  })

  it('changes nothing when disabled', async () => {
    const { changes } = await mountList(['hu', 'en'], { disabled: true })
    const buttons = [...document.querySelectorAll<HTMLButtonElement>('[data-role="item"] button')]
    expect(buttons.every((b) => b.disabled)).toBe(true)
    expect(item('hu').getAttribute('draggable')).toBe('false')
    drag('dragstart', item('en'))
    drag('dragover', item('hu'))
    drag('drop', item('hu'))
    await flushPromises()
    expect(changes).toEqual([])
    expect(document.querySelector<HTMLButtonElement>('.language-picker__trigger')?.disabled).toBe(
      true,
    )
  })
})
