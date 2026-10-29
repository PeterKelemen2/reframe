import { flushPromises, type VueWrapper } from '@vue/test-utils'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { afterEach, describe, expect, it } from 'vitest'

import { useSettingsStore } from '@/stores/settings'

import AppearanceSection from './AppearanceSection.vue'
import { mountSettings } from './testing'

globalThis.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }) as unknown as MediaQueryList

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  document.documentElement.className = ''
})

async function mountAppearance(language = 'en') {
  const result = await mountSettings(AppearanceSection, {
    setup: () => {
      const appearance = useSettingsStore().settings?.appearance
      if (appearance) appearance.ui_language = language
    },
  })
  mounted.push(result.wrapper)
  const buttons = (field: string) =>
    result.wrapper.findAllComponents(SelectButton).find((c) => c.attributes('data-field') === field)
  const languageSelect = () =>
    result.wrapper
      .findAllComponents(Select)
      .find((c) => c.attributes('data-field') === 'ui-language')
  return { ...result, buttons, language: languageSelect }
}

describe('the Appearance section', () => {
  it('switches the theme and density at once and saves them', async () => {
    const { buttons, server } = await mountAppearance()
    buttons('theme')?.vm.$emit('update:modelValue', 'dark')
    await flushPromises()
    buttons('density')?.vm.$emit('update:modelValue', 'compact')
    await flushPromises()
    expect(document.documentElement.classList.contains('reframe-dark')).toBe(true)
    expect(document.documentElement.dataset.density).toBe('compact')
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/appearance/theme', value: 'dark' }],
      [{ op: 'replace', path: '/appearance/density', value: 'compact' }],
    ])
    expect(buttons('theme')?.props('modelValue')).toBe('dark')
  })

  it('offers only the languages this build has, by name', async () => {
    const { language } = await mountAppearance()
    expect(language()?.props('options')).toEqual([
      { value: 'en', label: 'English', disabled: false },
    ])
    expect(language()?.props('modelValue')).toBe('en')
  })

  it('shows a saved language this build lacks as not available', async () => {
    const { language } = await mountAppearance('de')
    expect(language()?.props('options')).toContainEqual({
      value: 'de',
      label: 'German (not available)',
      disabled: true,
    })
  })

  it('saves the language at once', async () => {
    const { language, server } = await mountAppearance('de')
    language()?.vm.$emit('update:modelValue', 'en')
    await flushPromises()
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/appearance/ui_language', value: 'en' }],
    ])
  })
})
