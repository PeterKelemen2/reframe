import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import { useI18n } from 'vue-i18n'

import { createAppI18n } from '.'

// "no changed options | 1 changed option | {n} changed options"
const PLURAL_N = 'advanced.changedCount'
// "{count} track selected | {count} tracks selected"
const PLURAL_COUNT = 'tracks.bulk.selected'

describe('the app i18n', () => {
  it('writes a plural count with the locale, given alone or with named values', () => {
    const { t } = createAppI18n().global
    expect(t(PLURAL_N, 1234)).toBe('1,234 changed options')
    expect(t(PLURAL_N, 1)).toBe('1 changed option')
    expect(t(PLURAL_N, 0)).toBe('no changed options')
    expect(t(PLURAL_COUNT, { count: 2500 }, 2500)).toBe('2,500 tracks selected')
    expect(t(PLURAL_COUNT, {}, 1000)).toBe('1,000 tracks selected')
    expect(t(PLURAL_N, { other: 'x' }, 1234)).toBe('1,234 changed options')
    expect(t(PLURAL_N, { n: 1234 })).toBe('1,234 changed options')
    expect(t(PLURAL_N, { n: 1 })).toBe('1 changed option')
  })

  it('leaves other named values and text as they are', () => {
    const { t } = createAppI18n().global
    expect(t('clip.seconds', { seconds: '2.5' })).toBe('2.5 s')
    expect(t('advanced.title')).toBe('Advanced options')
  })

  it('formats the count in templates and in components that use useI18n', () => {
    const Counted = defineComponent({
      setup() {
        const { t } = useI18n()
        return () => h('p', [h('span', { class: 'script' }, t(PLURAL_N, 4096))])
      },
    })
    const wrapper = mount(Counted, { global: { plugins: [createAppI18n()] } })
    expect(wrapper.get('.script').text()).toBe('4,096 changed options')
    const inTemplate = mount(
      { template: `<p>{{ $t('${PLURAL_N}', 2048) }}</p>` },
      { global: { plugins: [createAppI18n()] } },
    )
    expect(inTemplate.text()).toBe('2,048 changed options')
  })
})
