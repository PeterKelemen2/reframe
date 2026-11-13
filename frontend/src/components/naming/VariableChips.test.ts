import { afterEach, describe, expect, it } from 'vitest'

import { mountBase } from '@/components/base/testing'

import { VARIABLES } from './testing/samples'
import VariableChips from './VariableChips.vue'

afterEach(() => {
  document.body.innerHTML = ''
})

describe('VariableChips', () => {
  it("shows each variable's value for the current source, or that it is empty", () => {
    const wrapper = mountBase(VariableChips, {
      props: { variables: VARIABLES, values: { main_title: 'Hacksaw.Ridge', season: '' } },
    })
    const chip = (name: string) => wrapper.get(`[data-variable="${name}"]`)
    expect(chip('main_title').text()).toBe('{main_title} Hacksaw.Ridge')
    expect(chip('season').text()).toBe('{season} empty')
    // The name holds the visible text, word for word (WCAG 2.5.3, Label in Name).
    expect(chip('main_title').attributes('aria-label')).toBe('Insert {main_title}: Hacksaw.Ridge')
    expect(chip('season').attributes('aria-label')).toBe('Insert {season}: empty for this file')
  })

  it('asks to insert the variable that was clicked', async () => {
    const wrapper = mountBase(VariableChips, { props: { variables: VARIABLES, values: null } })
    await wrapper.get('[data-variable="year"]').trigger('click')
    expect(wrapper.emitted('insert')).toEqual([['year']])
  })
})
