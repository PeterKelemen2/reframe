import { describe, expect, it } from 'vitest'

import type { NamingVariable } from '@/stores/system'

import { accept, completionAt, insertAt, matchSpecs, matchVariables } from './template'

function variable(name: string, kind: NamingVariable['kind'] = 'text'): NamingVariable {
  return { name, kind, group: 'name', description: name }
}

const VARIABLES = [
  variable('main_title'),
  variable('name'),
  variable('season', 'number'),
  variable('date', 'date'),
  variable('resolution'),
  variable('preset'),
]

describe('completionAt', () => {
  it('completes the name being typed after an open brace', () => {
    expect(completionAt('{main_title}.{re', 16)).toEqual({
      kind: 'name',
      start: 14,
      end: 16,
      query: 're',
    })
  })

  it('offers nothing outside a variable', () => {
    expect(completionAt('{main_title}.x', 14)).toBeNull()
    expect(completionAt('plain', 3)).toBeNull()
    expect(completionAt('{season:02}.', 12)).toBeNull()
  })

  it('takes a doubled brace as literal text', () => {
    expect(completionAt('{{x', 3)).toBeNull()
  })

  it('completes the format spec after the colon', () => {
    expect(completionAt('S{season:0', 10)).toEqual({
      kind: 'spec',
      name: 'season',
      start: 9,
      end: 10,
      query: '0',
    })
  })

  it('starts again at a second open brace before a close', () => {
    expect(completionAt('{ab {na', 7)).toMatchObject({ kind: 'name', start: 5, query: 'na' })
  })

  it('offers nothing when the text after the brace cannot be a name', () => {
    expect(completionAt('{a b', 4)).toBeNull()
  })
})

describe('accept', () => {
  it('closes the variable and puts the caret after it', () => {
    expect(accept('{re', { kind: 'name', start: 1, end: 3, query: 're' }, 'resolution')).toEqual({
      text: '{resolution}',
      caret: 12,
    })
  })

  it('replaces the rest of the name and keeps an existing close brace', () => {
    const text = '{resx}.mkv'
    expect(accept(text, { kind: 'name', start: 1, end: 3, query: 're' }, 'resolution')).toEqual({
      text: '{resolution}.mkv',
      caret: 12,
    })
  })

  it('keeps a spec that follows the name, with the caret before it', () => {
    const text = '{sea:02}'
    expect(accept(text, { kind: 'name', start: 1, end: 4, query: 'sea' }, 'season')).toEqual({
      text: '{season:02}',
      caret: 7,
    })
  })

  it('puts a spec in place up to the close brace', () => {
    const text = '{season:0x}'
    const completion = { kind: 'spec' as const, name: 'season', start: 8, end: 9, query: '0' }
    expect(accept(text, completion, '02')).toEqual({ text: '{season:02}', caret: 11 })
  })
})

describe('matchVariables', () => {
  it('lists the names that start with the query before those that contain it', () => {
    expect(matchVariables(VARIABLES, 're').map((v) => v.name)).toEqual(['resolution', 'preset'])
  })

  it('ignores case', () => {
    expect(matchVariables(VARIABLES, 'NA').map((v) => v.name)).toEqual(['name'])
  })
})

describe('matchSpecs', () => {
  it("offers the specs of the variable's kind", () => {
    expect(matchSpecs(VARIABLES, 'season', '').map((s) => s.spec)).toEqual(['02', '03'])
    expect(matchSpecs(VARIABLES, 'name', '').map((s) => s.spec)).toEqual([
      'upper',
      'lower',
      'title',
    ])
    expect(matchSpecs(VARIABLES, 'date', '%d').map((s) => s.spec)).toEqual(['%d.%m.%Y'])
  })

  it('offers none for an unknown variable', () => {
    expect(matchSpecs(VARIABLES, 'nope', '')).toEqual([])
  })
})

describe('insertAt', () => {
  it('replaces the selection and puts the caret after the insertion', () => {
    expect(insertAt('ab-cd', 2, 3, '{year}')).toEqual({ text: 'ab{year}cd', caret: 8 })
  })
})
