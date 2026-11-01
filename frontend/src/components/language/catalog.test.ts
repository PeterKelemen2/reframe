import { describe, expect, it } from 'vitest'

import { resolveTag, searchLanguages, writtenAs } from './catalog'
import { languages } from './testing'

const list = languages()
const tags = (found: { tag: string }[]) => found.map((language) => language.tag)
const first = (query: string, favourites: string[] = []) => {
  const { favourites: favs, others } = searchLanguages(list, query, favourites)
  return [...favs, ...others][0]?.tag
}

describe('resolveTag', () => {
  it('finds a listed language by any of its codes and by its tag in any case', () => {
    expect(resolveTag(list, 'hun')?.tag).toBe('hu')
    expect(resolveTag(list, 'ger')?.tag).toBe('de')
    expect(resolveTag(list, 'deu')?.tag).toBe('de')
    expect(resolveTag(list, 'pt_br')?.tag).toBe('pt-BR')
    expect(resolveTag(list, 'ZH-HANS')?.tag).toBe('zh-Hans')
  })

  it('makes a region or script variant of a listed base language, in canonical form', () => {
    const austrian = resolveTag(list, 'ger-at')
    expect(austrian).toMatchObject({
      tag: 'de-AT',
      iso639_2b: 'ger',
      iso639_2t: 'deu',
      english_name: 'German (Austria)',
      variant: true,
    })
    expect(resolveTag(list, 'zh-hans-tw')).toMatchObject({
      tag: 'zh-Hans-TW',
      english_name: 'Chinese (Simplified, Taiwan)',
    })
    expect(resolveTag(list, 'es-MX')?.english_name).toBe('Spanish (Mexico)')
  })

  it('offers no tag that names no known script or region, or has more subtags', () => {
    for (const text of [
      'en-XX',
      'en-Qaaa',
      'en-ZZ',
      'en-Zzzz',
      'sl-rozaj',
      'en-u-ca-gregory',
      'en-US-x-a',
      'x-foo',
      'yue',
      'und-BR',
      'Hungarian',
      'hu hu',
    ]) {
      expect(resolveTag(list, text)?.tag ?? `none for ${text}`).toBe(`none for ${text}`)
    }
  })
})

describe('writtenAs', () => {
  it('shows ISO 639-2/B for Matroska and WebM and ISO 639-2/T for MP4', () => {
    const german = list.find((language) => language.tag === 'de')!
    expect(writtenAs(german)).toEqual({ name: 'German', iso639_2: 'ger', tag: 'de' })
    expect(writtenAs(german, 'webm').iso639_2).toBe('ger')
    expect(writtenAs(german, 'mp4').iso639_2).toBe('deu')
  })
})

describe('searchLanguages', () => {
  it('finds a language by English name, native name, every ISO code and its full tag', () => {
    expect(first('Hungarian')).toBe('hu')
    expect(first('magyar')).toBe('hu')
    expect(first('MAGYAR')).toBe('hu')
    expect(first('hu')).toBe('hu')
    expect(first('hun')).toBe('hu')
    expect(first('fre')).toBe('fr')
    expect(first('fra')).toBe('fr')
    expect(first('francais')).toBe('fr')
    expect(first('pt-BR')).toBe('pt-BR')
    expect(first('es-419')).toBe('es-419')
    expect(first('zh-Hans')).toBe('zh-Hans')
    expect(first('sr-Latn')).toBe('sr-Latn')
    expect(first('brasil')).toBe('pt-BR')
  })

  it('puts the base language before its variants, and a name prefix before a substring', () => {
    expect(tags(searchLanguages(list, 'portug').others)).toEqual(['pt', 'pt-BR', 'pt-PT'])
    expect(tags(searchLanguages(list, 'gypt').others)).toEqual(['egy'])
    expect(tags(searchLanguages(list, 'e').others).slice(0, 2)).toEqual(['en', 'es'])
  })

  it('offers a typed variant that the list does not have', () => {
    expect(tags(searchLanguages(list, 'de-AT').others)).toEqual(['de-AT'])
  })

  it('lists the favourites first, in their order, then every other language', () => {
    const { favourites, others } = searchLanguages(list, '', ['pt-BR', 'hun', 'de-AT', 'hu'])
    expect(tags(favourites)).toEqual(['pt-BR', 'hu', 'de-AT'])
    expect(tags(others)).toEqual(tags(list).filter((tag) => tag !== 'pt-BR' && tag !== 'hu'))
  })

  it('keeps matching favourites in their own group when searching', () => {
    const found = searchLanguages(list, 'portug', ['pt-PT'])
    expect(tags(found.favourites)).toEqual(['pt-PT'])
    expect(tags(found.others)).toEqual(['pt', 'pt-BR'])
  })

  it('leaves out excluded languages in any form', () => {
    const found = searchLanguages(list, '', ['hu'], ['hun', 'en'])
    expect(tags(found.favourites)).toEqual([])
    expect(tags(found.others)).not.toContain('en')
    expect(tags(searchLanguages(list, 'hungarian', [], ['hu']).others)).toEqual([])
  })
})
