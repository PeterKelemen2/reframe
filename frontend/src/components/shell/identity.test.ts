import { describe, expect, it } from 'vitest'

import { episodeCode, identityParts, jobIdentity } from './identity'

function name(value: string, separator: string | null): string {
  return identityParts({ kind: 'episode', name: value, separator }, '/m/a.mkv', 'mkv').title
}

describe('the job identity line', () => {
  it('names an episode by its show, its code and the container', () => {
    expect(jobIdentity({ title: 'The Sopranos', season: 3, episode: 2, container: 'MKV' })).toBe(
      'The Sopranos · S03E02 · MKV',
    )
  })

  it('leaves out the parts that are not known', () => {
    expect(jobIdentity({ title: 'Heat', container: 'MKV' })).toBe('Heat · MKV')
    expect(jobIdentity({ title: 'Heat', container: null })).toBe('Heat')
    expect(jobIdentity({ title: 'Show', episode: 1071, container: 'MP4' })).toBe(
      'Show · E1071 · MP4',
    )
  })

  it('writes an episode code with two digits at least', () => {
    expect(episodeCode(1, 5)).toBe('S01E05')
    expect(episodeCode(12, 105)).toBe('S12E105')
    expect(episodeCode(null, 7)).toBe('E07')
    expect(episodeCode(3, null)).toBeNull()
  })

  it('takes the parsed name, else the file name without its extension', () => {
    expect(
      identityParts(
        { kind: 'episode', name: 'Anime Show', season: 1, episode: 2 },
        '/m/a.mkv',
        'mkv',
      ),
    ).toEqual({ title: 'Anime Show', season: 1, episode: 2, container: 'MKV' })
    expect(identityParts(null, '/m/Interview_raw.mov', 'mp4')).toEqual({
      title: 'Interview_raw',
      season: undefined,
      episode: undefined,
      container: 'MP4',
    })
    expect(identityParts({ kind: 'movie', name: ' ' }, 'C:\\v\\clip', null).title).toBe('clip')
  })

  it('puts spaces between the words of a name written with dots or underscores', () => {
    expect(name('Anime.Show', '.')).toBe('Anime Show')
    expect(name('The_Sopranos', '_')).toBe('The Sopranos')
    expect(name('Spider-Man', ' ')).toBe('Spider-Man')
    expect(name('Heat', null)).toBe('Heat')
  })
})
