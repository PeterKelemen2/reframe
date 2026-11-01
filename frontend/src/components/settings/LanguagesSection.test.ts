import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { deferred } from '@/api/testing/fakes'
import type { AppSettings } from '@/api/types'
import LanguageListEditor from '@/components/language/LanguageListEditor.vue'
import { languages } from '@/components/language/testing'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import LanguagesSection from './LanguagesSection.vue'
import { defaultSettings, mountSettings, refusal, systemInfo } from './testing'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

const LISTS = {
  favourites: { field: 'favourites', pointer: '/languages/favourites' },
  audio: { field: 'preferred-audio', pointer: '/languages/preferred_audio' },
  subtitle: { field: 'preferred-subtitle', pointer: '/languages/preferred_subtitle' },
} as const

function withLanguages(): AppSettings {
  return {
    ...defaultSettings(),
    languages: { favourites: ['hu'], preferred_audio: ['hu', 'en'], preferred_subtitle: [] },
  } as AppSettings
}

async function mountSection(readOnly = false) {
  const result = await mountSettings(LanguagesSection, {
    info: systemInfo({ settings_read_only: readOnly }),
    setup: () => {
      useSystemStore().languages = languages()
      useSettingsStore().settings = withLanguages()
    },
  })
  result.server.document = withLanguages()
  mounted.push(result.wrapper)
  const editor = (list: keyof typeof LISTS) =>
    result.wrapper
      .findAllComponents(LanguageListEditor)
      .find((c) => c.element.closest(`[data-field="${LISTS[list].field}"]`) !== null)!
  return { ...result, editor }
}

const shown = (list: keyof typeof LISTS) =>
  [
    ...document.querySelectorAll<HTMLElement>(
      `[data-field="${LISTS[list].field}"] [data-role="item"]`,
    ),
  ].map((item) => item.dataset.tag)

describe('the Languages section', () => {
  it('shows the three lists of the settings', async () => {
    await mountSection()
    expect(shown('favourites')).toEqual(['hu'])
    expect(shown('audio')).toEqual(['hu', 'en'])
    expect(shown('subtitle')).toEqual([])
  })

  it.each(Object.keys(LISTS) as (keyof typeof LISTS)[])(
    'saves a change of the %s list at once, at its own setting',
    async (list) => {
      const { editor, server } = await mountSection()
      editor(list).vm.$emit('update:modelValue', ['de', 'fr'])
      await flushPromises()
      expect(server.patches).toEqual([
        [{ op: 'replace', path: LISTS[list].pointer, value: ['de', 'fr'] }],
      ])
      expect(shown(list)).toEqual(['de', 'fr'])
    },
  )

  it('shows a refused list at its field and keeps the refused value', async () => {
    const { editor, server } = await mountSection()
    server.refuse = () => refusal(422, 'settings.invalid', 'The settings change is not valid')
    editor('audio').vm.$emit('update:modelValue', ['en', 'hu'])
    await flushPromises()
    const issues = document.querySelectorAll(`[data-field="preferred-audio"] .rf-field__issue`)
    expect([...issues].map((issue) => issue.textContent)).toEqual([
      'Error: The settings change is not valid',
    ])
    expect(document.querySelectorAll('.rf-field__issue')).toHaveLength(1)
    expect(shown('audio')).toEqual(['en', 'hu'])
  })

  it('shows a change before the answer, so that a second change builds on the first', async () => {
    const { editor, server } = await mountSection()
    const answer = deferred()
    server.on('PUT /api/settings', async ({ body }) => {
      await answer.promise
      const ops = body as { path: string; value: string[] }[]
      const next = structuredClone(server.document)
      next.languages = { ...next.languages, favourites: ops[0]!.value }
      server.document = next
      return { settings: next, changes: [], saved: true, warnings: [] }
    })
    editor('favourites').vm.$emit('update:modelValue', ['hu', 'de'])
    await flushPromises()
    expect(shown('favourites')).toEqual(['hu', 'de'])
    expect(editor('favourites').props('modelValue')).toEqual(['hu', 'de'])
    answer.resolve()
    await flushPromises()
    expect(shown('favourites')).toEqual(['hu', 'de'])
  })

  it('is read-only when the settings are', async () => {
    const { editor } = await mountSection(true)
    for (const list of Object.keys(LISTS) as (keyof typeof LISTS)[]) {
      expect(editor(list).props('disabled')).toBe(true)
    }
  })
})
