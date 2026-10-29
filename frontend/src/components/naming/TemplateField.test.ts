import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { mountBase } from '@/components/base/testing'
import type { NamingVariable } from '@/stores/system'

import TemplateField from './TemplateField.vue'

const VARIABLES: NamingVariable[] = [
  { name: 'main_title', group: 'name', kind: 'text', description: 'The main title' },
  { name: 'resolution', group: 'media', kind: 'text', description: '1080p…' },
  { name: 'season', group: 'name', kind: 'number', description: 'Season number' },
]

function mountField(value: string) {
  const wrapper = mountBase(TemplateField, {
    props: {
      modelValue: value,
      variables: VARIABLES,
      'onUpdate:modelValue': (next: string) => wrapper.setProps({ modelValue: next }),
    },
  })
  return wrapper
}

async function typeAtEnd(wrapper: ReturnType<typeof mountField>, text: string): Promise<void> {
  const input = wrapper.get('input').element as HTMLInputElement
  input.focus()
  input.value += text
  input.setSelectionRange(input.value.length, input.value.length)
  await wrapper.get('input').trigger('input')
  await flushPromises()
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('TemplateField', () => {
  it('lists the matching variables after an open brace', async () => {
    const wrapper = mountField('{main_title}.')
    await typeAtEnd(wrapper, '{re')
    const options = wrapper.findAll('[role="option"]').map((option) => option.find('code').text())
    expect(options).toEqual(['{resolution}'])
    expect(wrapper.get('input').attributes('aria-expanded')).toBe('true')
  })

  it('takes the active variable with Enter and closes the list', async () => {
    const wrapper = mountField('')
    await typeAtEnd(wrapper, '{')
    await wrapper.get('input').trigger('keydown', { key: 'ArrowDown' })
    await wrapper.get('input').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.props('modelValue')).toBe('{resolution}')
    expect(wrapper.find('[role="listbox"]').isVisible()).toBe(false)
  })

  it("lists the variable's format specs after the colon", async () => {
    const wrapper = mountField('S')
    await typeAtEnd(wrapper, '{season:')
    const options = wrapper.findAll('[role="option"] code').map((option) => option.text())
    expect(options).toEqual(['{season:02}', '{season:03}'])
  })

  it('closes the list with Escape without changing the text', async () => {
    const wrapper = mountField('')
    await typeAtEnd(wrapper, '{ma')
    await wrapper.get('input').trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[role="listbox"]').isVisible()).toBe(false)
    expect(wrapper.props('modelValue')).toBe('{ma')
  })

  it('inserts at the caret it had last', async () => {
    const wrapper = mountField('{name} {year}')
    const input = wrapper.get('input').element as HTMLInputElement
    input.focus()
    input.setSelectionRange(6, 6)
    await wrapper.get('input').trigger('click')
    await wrapper.get('input').trigger('blur')
    ;(wrapper.vm as unknown as { insert(text: string): void }).insert('{season:02}')
    await flushPromises()
    expect(wrapper.props('modelValue')).toBe('{name}{season:02} {year}')
  })
})
