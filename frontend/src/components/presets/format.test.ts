import { describe, expect, it } from 'vitest'

import { exportFileName, importClashes, pathWords, valueWords, type Words } from './format'
import { preset, userPreset } from './testing'

const words: Words = {
  field: (key) =>
    ({
      audio_defaults: 'Audio defaults',
      codec_rules: 'Codec rule',
      max_bitrate: 'Maximum bitrate',
    })[key],
  none: 'none',
  empty: 'empty',
  on: 'on',
  off: 'off',
}

describe('the words of a change', () => {
  it('names each part of a path, numbering list items from one', () => {
    expect(pathWords('audio_defaults.codec_rules[0].max_bitrate', words)).toBe(
      'Audio defaults › Codec rule 1 › Maximum bitrate',
    )
  })

  it('shows a key without a message with spaces and a capital', () => {
    expect(pathWords('audio_defaults.passthru.fallback_encoder', words)).toBe(
      'Audio defaults › Passthru › Fallback encoder',
    )
  })

  it('shows values in words: none, on and off, lists, long values cut', () => {
    expect(valueWords(null, words)).toBe('none')
    expect(valueWords(true, words)).toBe('on')
    expect(valueWords(false, words)).toBe('off')
    expect(valueWords('', words)).toBe('empty')
    expect(valueWords(22.5, words)).toBe('22.5')
    expect(valueWords([], words)).toBe('none')
    expect(valueWords(['ac3', 'eac3'], words)).toBe('ac3, eac3')
    expect(valueWords({ max_bitrate: 160, codec: 'aac', name: null }, words)).toBe(
      'Maximum bitrate: 160 · Codec: aac',
    )
    const long = valueWords('x'.repeat(200), words)
    expect(long).toHaveLength(80)
    expect(long.endsWith('…')).toBe(true)
  })

  it('shows a value with words of its own by them, by its path, also inside an object', () => {
    const known: Words = {
      ...words,
      known: (path, value) =>
        path === 'video.rate_control' && value !== null ? 'CQ 27' : undefined,
    }
    expect(valueWords({ mode: 'quality', value: 27 }, known, 'video.rate_control')).toBe('CQ 27')
    expect(valueWords({ rate_control: { mode: 'quality' } }, known, 'video')).toBe(
      'Rate control: CQ 27',
    )
    expect(valueWords(null, known, 'video.rate_control')).toBe('none')
  })
})

describe('the clashes of an import file', () => {
  const known = [preset('h265-mkv-1080p', 'H.265 MKV 1080p'), userPreset('u1', 'Mine')]

  it('finds presets of the file whose id or name is known, names without case or extra spaces', () => {
    const file = JSON.stringify({
      presets: [
        { id: 'u1', name: 'Something else' },
        { id: 'x', name: '  h.265   mkv 1080P ' },
        { id: 'y', name: 'New' },
      ],
    })
    expect(importClashes(file, known)).toEqual(['Something else', '  h.265   mkv 1080P '])
  })

  it('cannot tell for a file that is not a preset file', () => {
    expect(importClashes('not json', known)).toBeNull()
    expect(importClashes('[1]', known)).toBeNull()
    expect(importClashes('{"name": "x"}', known)).toBeNull()
  })
})

describe('the name of an export file', () => {
  it('is the preset’s name without characters a file name cannot have', () => {
    expect(exportFileName([userPreset('u1', 'Anime: 1080p / 10-bit')])).toBe(
      'Anime_ 1080p _ 10-bit.json',
    )
  })

  it('is a general name for several presets', () => {
    expect(exportFileName([userPreset('a', 'A'), userPreset('b', 'B')])).toBe(
      'reframe-presets.json',
    )
  })
})
