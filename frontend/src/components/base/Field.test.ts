import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'

import type { ValidationIssue } from '@/api/types'
import { REVEALED_CLASS } from '@/composables/useReveal'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import Field from './Field.vue'
import { mountBase } from './testing'
import type { FieldSlotProps } from './types'

function issue(severity: ValidationIssue['severity'], message: string, path = 'video.encoder') {
  return { severity, code: `test.${severity}`, path, message, fixes: [] }
}

const control = {
  default: (p: FieldSlotProps) =>
    h('input', { id: p.id, 'data-invalid': String(p.invalid), class: 'control' }),
}

function mountField(props: Record<string, unknown>) {
  return mountBase(Field, { props: { label: 'Encoder', ...props }, slots: control })
}

afterEach(() => {
  document.body.replaceChildren()
})

describe('Field', () => {
  it("shows the store's issues for its path, most severe first, and marks an error invalid", async () => {
    const wrapper = mountField({ path: 'video.encoder' })
    useValidationStore().issues = [
      issue('warning', 'Slow'),
      issue('error', 'Not available'),
      issue('error', 'Elsewhere', 'audio[0].encoder'),
    ]
    await flushPromises()
    expect(wrapper.findAll('.rf-field__issue').map((li) => li.text())).toEqual([
      'Error: Not available',
      'Warning: Slow',
    ])
    expect(wrapper.classes()).toContain('rf-field--error')
    const input = wrapper.get('input.control')
    expect(input.attributes('data-invalid')).toBe('true')
    expect(wrapper.get('label').attributes('for')).toBe(input.attributes('id'))
    expect(input.attributes('aria-describedby')).toBe(wrapper.get('ul').attributes('id'))
  })

  it('shows its own issues instead of the store’s; a warning is not invalid', async () => {
    const wrapper = mountField({ path: 'video.encoder', issues: [issue('warning', 'Own')] })
    useValidationStore().issues = [issue('error', 'From the store')]
    await flushPromises()
    expect(wrapper.findAll('.rf-field__issue').map((li) => li.text())).toEqual(['Warning: Own'])
    expect(wrapper.classes()).toContain('rf-field--warning')
    expect(wrapper.get('input.control').attributes('data-invalid')).toBe('false')
  })

  it('drops the description and the outline when the issues go away', async () => {
    const wrapper = mountField({ path: 'video.encoder' })
    const validation = useValidationStore()
    validation.issues = [issue('error', 'Not available')]
    await flushPromises()
    expect(wrapper.get('input.control').attributes('aria-describedby')).toBeDefined()
    validation.issues = []
    await flushPromises()
    expect(wrapper.find('ul').exists()).toBe(false)
    expect(wrapper.get('input.control').attributes('aria-describedby')).toBeUndefined()
    expect(wrapper.classes()).not.toContain('rf-field--error')
  })

  it('shows the override dot only when overridden', async () => {
    const wrapper = mountField({})
    expect(wrapper.find('.rf-field__override').exists()).toBe(false)
    await wrapper.setProps({ overridden: true })
    expect(wrapper.get('.rf-field__override').attributes('aria-label')).toBe(
      'Differs from the group',
    )
  })

  it('opens its help from a named button', async () => {
    const wrapper = mountField({ help: 'Lower is better.' })
    const button = wrapper.get('button[aria-label="About Encoder"]')
    expect(button.attributes('aria-expanded')).toBe('false')
    await button.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('Lower is better.')
    expect(button.attributes('aria-expanded')).toBe('true')
  })

  it('is the target of ui.reveal for its path', async () => {
    Element.prototype.scrollIntoView = vi.fn<() => void>()
    const wrapper = mountField({ path: 'video.encoder' })
    useUiStore().reveal('video.encoder')
    await flushPromises()
    await nextTick()
    expect(wrapper.classes()).toContain(REVEALED_CLASS)
    expect(document.activeElement).toBe(wrapper.get('input.control').element)
  })
})
