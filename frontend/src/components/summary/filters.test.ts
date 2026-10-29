import { describe, expect, it } from 'vitest'

import { filterChips } from './filters'
import { sampleDefinitions } from './testing'

const DEFINITIONS = sampleDefinitions()

function config(preset: string, implementation: string | null = null) {
  return { preset, tune: null, custom: null, implementation }
}

describe('the filter chips', () => {
  it('show the filters that are on and Deinterlace, Colorspace and Tone mapping when off, in chain order', () => {
    const chips = filterChips(
      { denoise: config('medium'), interlace_detection: config('default') },
      DEFINITIONS,
    )
    expect(chips).toEqual([
      { id: 'interlace_detection', label: 'Interlace detection', value: 'Default' },
      { id: 'deinterlace', label: 'Deinterlace', value: null },
      { id: 'denoise', label: 'Denoise', value: 'Medium' },
      { id: 'tonemap', label: 'HDR → SDR tone mapping', value: null },
      { id: 'colorspace', label: 'Colorspace', value: null },
    ])
  })

  it('names the preset of the chosen implementation', () => {
    const chips = filterChips(
      { deinterlace: config('skip-spatial', 'yadif'), colorspace: config('bt709') },
      DEFINITIONS,
    )
    expect(chips.find((chip) => chip.id === 'deinterlace')?.value).toBe('Skip spatial check')
    expect(chips.find((chip) => chip.id === 'colorspace')?.value).toBe('BT.709')
  })

  it('still lists the filters before the definitions have loaded', () => {
    expect(
      filterChips({ sharpen: config('light') }, null).map((chip) => [chip.id, chip.value]),
    ).toEqual([
      ['deinterlace', null],
      ['colorspace', null],
      ['tonemap', null],
      ['sharpen', 'light'],
    ])
  })
})
