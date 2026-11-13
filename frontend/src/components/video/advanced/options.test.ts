import { describe, expect, it } from 'vitest'

import type { EncoderOption } from '@/api/types'
import { formatters } from '@/components/summary/testing'
import { encoderDefs, videoOf } from '@/components/video/testing'
import { sampleJob } from '@/editor/testing/samples'

import { categoriesOf, categoryName, CUSTOM_CATEGORY, defaultText, optionPointer } from './options'
import recorded from './testing/x265-options.json'

const { t, n } = formatters()
const x265 = encoderDefs().libx265!
const options = recorded as unknown as EncoderOption[]

function option(key: string): EncoderOption {
  return options.find((candidate) => candidate.key === key)!
}

function fixed(value: number): EncoderOption {
  return { ...option('keyint'), default: { kind: 'fixed', value } } as EncoderOption
}

function video(changes: { preset?: string | null; tune?: string | null } = {}) {
  return { ...videoOf(sampleJob()), ...changes }
}

describe('the categories', () => {
  it("come in the core's panel order, an unknown one after them, the custom parameters last", () => {
    const future = { ...option('keyint'), key: 'future', category: 'Future' }
    const ids = categoriesOf([future, ...options]).map((category) => category.id)
    expect(ids).toEqual([
      'Rate control',
      'Frame types / GOP',
      'Psycho-visual',
      'HDR / colour',
      'Performance',
      'Future',
      CUSTOM_CATEGORY,
    ])
    expect(categoryName('Future', t)).toBe('Future')
    expect(categoryName('Frame types / GOP', t)).toBe('Frame types / GOP')
    expect(categoryName(CUSTOM_CATEGORY, t)).toBe('Custom parameters')
  })
})

describe('the default text', () => {
  it("names the speed preset's value and the preset", () => {
    expect(defaultText(option('bframes'), video({ preset: 'slow' }), x265, t, n)).toBe(
      '4 frames (preset Slow)',
    )
    expect(defaultText(option('bframes'), video({ preset: 'slower' }), x265, t, n)).toBe(
      '8 frames (preset Slower)',
    )
  })

  it("takes the encoder's default preset for a job without one", () => {
    // libx265's default preset is medium.
    expect(defaultText(option('b-adapt'), video({ preset: null }), x265, t, n)).toBe(
      'Full (preset Medium)',
    )
  })

  it('says when the tune changes it', () => {
    expect(
      defaultText(option('bframes'), video({ preset: 'slow', tune: 'animation' }), x265, t, n),
    ).toBe('4 frames (preset Slow); tune Animation changes it')
    expect(
      defaultText(option('bframes'), video({ preset: 'slow', tune: 'grain' }), x265, t, n),
    ).toBe('4 frames (preset Slow)')
  })

  it('says when the option is not used at the preset', () => {
    const partial = {
      ...option('bframes'),
      default: { kind: 'preset', values: { slow: 4 } },
    } as EncoderOption
    expect(defaultText(partial, video({ preset: 'ultrafast' }), x265, t, n)).toBe(
      'not used at preset Ultrafast',
    )
  })

  it('gives a fixed value with its unit, and a switch as on or off', () => {
    expect(defaultText(option('keyint'), video(), x265, t, n)).toBe('250 frames')
    expect(defaultText(option('b-intra'), video({ preset: 'slow' }), x265, t, n)).toBe(
      'off (preset Slow)',
    )
  })

  it('says the encoder decides, with its note', () => {
    expect(defaultText(option('min-keyint'), video(), x265, t, n)).toBe(
      'the encoder decides (auto, from the frame rate)',
    )
    const silent = { ...option('pools'), default: { kind: 'encoder', note: '' } } as EncoderOption
    expect(defaultText(silent, video(), x265, t, n)).toBe('the encoder decides')
  })

  it("writes a number in the app's locale, without grouping its digits", () => {
    const german = formatters('de')
    expect(defaultText(fixed(0.75), video(), x265, german.t, german.n)).toBe('0,75 frames')
    expect(defaultText(fixed(12500), video(), x265, german.t, german.n)).toBe('12500 frames')
  })
})

describe('the helpers', () => {
  it('escapes a key as a JSON pointer token', () => {
    expect(optionPointer('psy-rd')).toBe('/video/advanced/psy-rd')
    expect(optionPointer('a/b~c')).toBe('/video/advanced/a~1b~0c')
  })
})
