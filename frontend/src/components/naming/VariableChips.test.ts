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
    expect(wrapper.get('[data-variable="main_title"]').text()).toBe('{main_title}Hacksaw.Ridge')
    expect(wrapper.get('[data-variable="season"]').text()).toBe('{season}empty')
    expect(wrapper.get('[data-variable="main_title"]').attributes('aria-label')).toBe(
      'Insert {main_title} (now: Hacksaw.Ridge)',
    )
  })

  it('asks to insert the variable that was clicked', async () => {
    const wrapper = mountBase(VariableChips, { props: { variables: VARIABLES, values: null } })
    await wrapper.get('[data-variable="year"]').trigger('click')
    expect(wrapper.emitted('insert')).toEqual([['year']])
  })
})
