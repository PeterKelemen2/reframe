import { describe, expect, it } from 'vitest'

import type { Language } from '@/api/types'

import { LANGUAGE_SLOTS, languageKey, languageSlot, slotColor } from './languageColor'

function language(tag: string, iso3: string, variant = false): Language {
  const base = tag.split('-')[0] ?? tag
  return {
    tag,
    iso639_1: base,
    iso639_2b: iso3,
    iso639_2t: iso3,
    iso639_3: iso3,
    english_name: tag,
    native_name: tag,
    variant,
  }
}

const LANGUAGES = [
  language('hu', 'hun'),
  language('en', 'eng'),
  language('en-GB', 'eng', true),
  language('de', 'deu'),
  language('ja', 'jpn'),
  language('pt', 'por'),
  language('pt-BR', 'por', true),
]

describe('languageSlot', () => {
  it('gives the preferred languages the first slots in their order', () => {
    const preferred = ['hun', 'en']
    expect(languageSlot('hu', LANGUAGES, preferred)).toBe(1)
    expect(languageSlot('eng', LANGUAGES, preferred)).toBe(2)
  })

  it('gives one colour to every code and variant of a language', () => {
    expect(languageKey(LANGUAGES, 'en-GB')).toBe(languageKey(LANGUAGES, 'eng'))
    expect(languageSlot('pt-BR', LANGUAGES, ['pt'])).toBe(1)
  })

  it('puts any other language on a free slot, the same one every time', () => {
    const preferred = ['hu', 'en']
    const slot = languageSlot('ja', LANGUAGES, preferred)
    expect(slot).toBeGreaterThan(2)
    expect(slot).toBeLessThanOrEqual(LANGUAGE_SLOTS)
    expect(languageSlot('jpn', LANGUAGES, preferred)).toBe(slot)
  })

  it('draws an undetermined language in the neutral colour', () => {
    for (const tag of ['und', '', null, undefined]) {
      expect(languageSlot(tag, LANGUAGES, ['hu'])).toBe('und')
    }
    expect(slotColor('und')).toBe('var(--rf-lang-und)')
  })

  it('keeps a slot for a language the list does not know', () => {
    const slot = languageSlot('xyz', LANGUAGES, [])
    expect(slot).toBeGreaterThanOrEqual(1)
    expect(languageSlot('xyz', LANGUAGES, [])).toBe(slot)
  })
})
