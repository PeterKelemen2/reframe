import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import { mountShell } from '@/components/shell/testing'
import type { PresetCategory } from '@/stores/presets'

import PresetTree from './PresetTree.vue'
import { preset, userPreset } from './testing'

const categories: PresetCategory[] = [
  {
    name: 'General',
    presets: [preset('fast', 'Fast 1080p30'), preset('very-fast', 'Very Fast 1080p30')],
  },
  { name: 'Custom', presets: [userPreset('u1', 'Mine')] },
]

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountTree(selectedId: string | null = 'fast') {
  const { wrapper } = await mountShell(PresetTree, {
    props: { categories, selectedId, defaultId: 'very-fast', currentId: 'u1' },
  })
  mounted.push(wrapper)
  return wrapper
}

function focused(): string | null {
  const element = document.activeElement as HTMLElement | null
  return element?.dataset.preset ?? element?.dataset.category ?? null
}

async function press(key: string): Promise<void> {
  ;(document.activeElement as HTMLElement).dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true }),
  )
  await nextTick()
  await nextTick()
}

describe('the preset tree', () => {
  it('shows the categories with their presets, built-ins locked and the default starred', async () => {
    const wrapper = await mountTree()
    expect(
      wrapper.findAll('[data-category]').map((item) => item.attributes('data-category')),
    ).toEqual(['General', 'Custom'])
    const fast = wrapper.find('[data-preset="fast"]')
    expect(fast.text()).toContain('Built-in, read-only')
    expect(wrapper.find('[data-preset="u1"]').text()).not.toContain('Built-in')
    expect(wrapper.find('[data-preset="very-fast"]').text()).toContain('Default')
    expect(wrapper.find('[data-preset="u1"]').text()).toContain('used by the open job')
    expect(fast.attributes('aria-selected')).toBe('true')
    expect(fast.attributes('tabindex')).toBe('0')
  })

  it('moves with the arrow keys and selects what it moves to', async () => {
    const wrapper = await mountTree()
    ;(wrapper.find('[data-preset="fast"]').element as HTMLElement).focus()
    await press('ArrowDown')
    expect(focused()).toBe('very-fast')
    await press('ArrowDown')
    expect(focused()).toBe('Custom')
    await press('ArrowDown')
    expect(focused()).toBe('u1')
    await press('ArrowUp')
    expect(focused()).toBe('Custom')
    await press('Home')
    expect(focused()).toBe('General')
    await press('End')
    expect(focused()).toBe('u1')
    expect(wrapper.emitted('select')).toEqual([['very-fast'], ['u1'], ['u1']])
  })

  it('closes and opens a category with left and right, and goes from a preset to its category', async () => {
    const wrapper = await mountTree()
    ;(wrapper.find('[data-preset="very-fast"]').element as HTMLElement).focus()
    await press('ArrowLeft')
    expect(focused()).toBe('General')
    await press('ArrowLeft')
    expect(wrapper.find('[data-category="General"]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-preset="fast"]').exists()).toBe(false)
    await press('ArrowDown')
    expect(focused()).toBe('Custom')
    await press('ArrowUp')
    await press('ArrowRight')
    expect(wrapper.find('[data-preset="fast"]').exists()).toBe(true)
    await press('ArrowRight')
    expect(focused()).toBe('fast')
  })

  it('applies a preset with Enter and opens or closes a category with it', async () => {
    const wrapper = await mountTree()
    ;(wrapper.find('[data-preset="fast"]').element as HTMLElement).focus()
    await press('Enter')
    expect(wrapper.emitted('apply')).toEqual([['fast']])
    ;(wrapper.find('[data-category="Custom"]').element as HTMLElement).focus()
    await press('Enter')
    expect(wrapper.find('[data-preset="u1"]').exists()).toBe(false)
    expect(wrapper.emitted('apply')).toHaveLength(1)
  })

  it('asks to delete a user preset with Delete, never a built-in one', async () => {
    const wrapper = await mountTree('u1')
    ;(wrapper.find('[data-preset="u1"]').element as HTMLElement).focus()
    await press('Delete')
    ;(wrapper.find('[data-preset="fast"]').element as HTMLElement).focus()
    await press('Delete')
    expect(wrapper.emitted('remove')).toEqual([['u1']])
  })

  it('applies a preset on double-click', async () => {
    const wrapper = await mountTree()
    await wrapper.find('[data-preset="u1"]').trigger('dblclick')
    expect(wrapper.emitted('apply')).toEqual([['u1']])
  })

  it('opens the category of a preset chosen elsewhere', async () => {
    const wrapper = await mountTree('fast')
    ;(wrapper.find('[data-category="Custom"]').element as HTMLElement).focus()
    await press('ArrowLeft')
    expect(wrapper.find('[data-preset="u1"]').exists()).toBe(false)
    await wrapper.setProps({ selectedId: 'u1' })
    expect(wrapper.find('[data-preset="u1"]').attributes('tabindex')).toBe('0')
  })
})
