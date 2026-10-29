import { describe, expect, it } from 'vitest'

import { segments, toneOf } from './spans'

function span(field: string, start: number, end: number, text: string) {
  return { field, start, end, text }
}

describe('segments', () => {
  it('cuts the name into recognised parts and the text between them', () => {
    const text = 'Hacksaw.Ridge.2016'
    const result = segments(text, [
      span('year', 14, 18, '2016'),
      span('name', 0, 13, 'Hacksaw.Ridge'),
    ])
    expect(result.map((s) => [s.text, s.span?.field ?? null])).toEqual([
      ['Hacksaw.Ridge', 'name'],
      ['.', null],
      ['2016', 'year'],
    ])
  })

  it('shows characters that two properties claim once', () => {
    const result = segments('HEVC-GRP', [
      span('video_codec', 0, 4, 'HEVC'),
      span('video_profile', 0, 4, 'HEVC'),
      span('release_group', 5, 8, 'GRP'),
    ])
    expect(result.map((s) => s.text).join('')).toBe('HEVC-GRP')
    expect(result.filter((s) => s.span !== null)).toHaveLength(2)
  })

  it('counts positions in code points, as the server does', () => {
    const result = segments('😀.Title', [span('name', 2, 7, 'Title')])
    expect(result.at(-1)).toMatchObject({ text: 'Title', span: { field: 'name' } })
  })
})

describe('toneOf', () => {
  it('groups the episode parts and leaves unknown properties as other tags', () => {
    expect(toneOf('episode_code')).toBe('episode')
    expect(toneOf('season')).toBe('episode')
    expect(toneOf('audio_codec')).toBe('other')
  })
})
