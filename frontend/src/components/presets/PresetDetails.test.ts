import { afterEach, describe, expect, it } from 'vitest'

import type { Preset } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { sampleDefinitions } from '@/components/summary/testing'
import { useSystemStore } from '@/stores/system'

import PresetDetails from './PresetDetails.vue'
import { userPreset } from './testing'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function summary(preset: Preset): Promise<(string | undefined)[][]> {
  const { wrapper } = await mountShell(PresetDetails, {
    props: { preset, isDefault: false, canApply: false, canUpdate: false, busy: false },
    setup: () => (useSystemStore().definitions = sampleDefinitions()),
  })
  mounted.push(wrapper)
  return [...document.querySelectorAll('.preset-details__summary .rf-kv')].map((row) => [
    row.querySelector('dt')?.textContent ?? undefined,
    row.querySelector('dd')?.textContent?.trim(),
  ])
}

describe('the preset summary', () => {
  it('says that the explicit rules of a saved group choose its tracks, not its defaults', async () => {
    const rule = (kind: 'audio' | 'subtitle', stream: number) => ({
      selector: { kind, stream },
      multiple: false,
      settings: {},
      required: true,
    })
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
})
