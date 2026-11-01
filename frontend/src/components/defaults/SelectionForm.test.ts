import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import type { AppSettings } from '@/api/types'
import { languages } from '@/components/language/testing'
import { mountShell } from '@/components/shell/testing'
import { useDefaultsStore } from '@/stores/defaults'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import { completeAudio, completeSubtitles } from './model'
import SelectionForm from './SelectionForm.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountForm(kind: 'audio' | 'subtitles'): Promise<void> {
  const { wrapper } = await mountShell(SelectionForm, {
    setup: () => {
      useSystemStore().languages = languages()
      useSettingsStore().settings = {
        languages: { favourites: [], preferred_audio: ['hu', 'en'], preferred_subtitle: ['de'] },
      } as unknown as AppSettings
      const defaults = useDefaultsStore()
      defaults.kind = kind
      defaults.audio = completeAudio(undefined)
      defaults.subtitles = completeSubtitles(undefined)
    },
  })
  mounted.push(wrapper)
}

const fromSettings = () =>
  document.querySelector<HTMLInputElement>('[data-role="languages-from-settings"] input')!

async function toggle(): Promise<void> {
  fromSettings().click()
  await flushPromises()
}

describe('the selection settings', () => {
  it("start an own language list from Settings' preferred languages, and go back to Settings", async () => {
    await mountForm('audio')
    expect(document.querySelector('.defaults-selection__hint')?.textContent).toContain(
      'Hungarian, English',
    )
    await toggle()
    const defaults = useDefaultsStore()
    expect(defaults.audio!.selection!.languages).toEqual(['hu', 'en'])
    expect(
      [...document.querySelectorAll('[data-role="item"]')].map((item) =>
        item.getAttribute('data-tag'),
      ),
    ).toEqual(['hu', 'en'])
    await toggle()
    expect(defaults.audio!.selection!.languages).toBeNull()
  })

  it('edit the subtitle defaults in the subtitle dialog, with the subtitle languages', async () => {
    await mountForm('subtitles')
    await toggle()
    const defaults = useDefaultsStore()
    expect(defaults.subtitles!.selection!.languages).toEqual(['de'])
    expect(defaults.audio!.selection!.languages).toBeNull()
  })
})
