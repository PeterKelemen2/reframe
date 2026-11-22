import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import type { Preset } from '@/api/types'
import { mountShell, setAppLocale } from '@/components/shell/testing'
import { sampleDefinitions } from '@/components/summary/testing'
import { useSystemStore } from '@/stores/system'

import PresetDetails from './PresetDetails.vue'
import { userPreset } from './testing'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function summary(preset: Preset, locale = 'en'): Promise<(string | undefined)[][]> {
  const { wrapper } = await mountShell(PresetDetails, {
    props: { preset, isDefault: false, canApply: false, canUpdate: false, busy: false },
    setup: () => (useSystemStore().definitions = sampleDefinitions()),
  })
  mounted.push(wrapper)
  setAppLocale(wrapper, locale)
  await nextTick()
  return [...document.querySelectorAll('.preset-details__summary .rf-kv')].map((row) => [
    row.querySelector('dt')?.textContent ?? undefined,
    row.querySelector('dd')?.textContent?.trim(),
  ])
}

function rule(kind: 'audio' | 'subtitle', stream: number) {
  return { selector: { kind, stream }, multiple: false, settings: {}, required: true }
}

describe('the preset summary', () => {
  it('says that the explicit rules of a saved group choose its tracks, not its defaults', async () => {
    const preset = {
      ...userPreset('u1', 'Anime BD'),
      audio_rules: [rule('audio', 1), rule('audio', 2)],
      subtitle_rules: [rule('subtitle', 4)],
    } as unknown as Preset
    const rows = await summary(preset)
    expect(rows).toContainEqual(['Audio tracks', "Chosen by the preset's 2 track rules"])
    expect(rows).toContainEqual(['Subtitle tracks', "Chosen by the preset's 1 track rule"])
    expect(rows.map(([label]) => label)).not.toContain('Audio encoding')
    expect(rows.map(([label]) => label)).not.toContain('Burn in')
  })

  it('writes numbers and lists as the locale does', async () => {
    const base = userPreset('u1', 'Remux')
    const preset = {
      ...base,
      video: { ...base.video, rate_control: { mode: 'bitrate', kbps: 12000, two_pass: false } },
      audio_defaults: {
        selection: { languages: ['jpn', 'eng', 'fra'], tracks_per_language: 'first' },
        codec_rules: [
          { languages: null, codec: 'aac', mixdown: 'stereo', max_bitrate: 1536 },
          { languages: null, codec: 'aac', mixdown: 'stereo', max_bitrate: null },
        ],
        passthru: { allowed: ['ac3', 'dts', 'truehd'], fallback_encoder: 'aac' },
      },
    } as unknown as Preset
    const text = (await summary(preset, 'de')).map(([, value]) => value).join('\n')
    expect(text).toContain('12.000 kb/s')
    expect(text).toContain('jpn, eng und fra')
    expect(text).toContain('up to 1.536 kb/s, AAC')
    expect(text).toContain('ac3, dts und truehd')
  })
})
