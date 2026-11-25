import { describe, expect, it } from 'vitest'

import { identityLine, parseFileName } from './identity'
import { job } from './testing'

function withSource(path: string, output: object = { path: '/out/x.mkv', container: 'mkv' }) {
  const base = job('a')
  return { ...base, settings: { ...base.settings, source: { path }, output } } as typeof base
}

describe('a job’s identity line', () => {
  it.each([
    ['The.Sopranos.S03E02.Proshai.Livushka.1080p.BluRay.REMUX.mkv', 'The Sopranos', 'S03E02'],
    ['The Sopranos - s3e2 - Proshai, Livushka.mkv', 'The Sopranos', 'S03E02'],
    ['Anime_Show_S01E05_[GRP].mkv', 'Anime Show', 'S01E05'],
    ['Show.Name.S01E01E02.720p.mkv', 'Show Name', 'S01E01'],
    ['Firefly 1x04 Jaynestown.mkv', 'Firefly', 'S01E04'],
    ['Heat (1995).mkv', 'Heat (1995)', null],
    ['Heat.1995.1080p.BluRay.x264-GRP.mkv', 'Heat 1995', null],
    ['interview_raw.mov', 'interview raw', null],
    ['S02E03.mkv', 'S02E03', null],
  ])('reads %s as %s, %s', (name, title, episode) => {
    expect(parseFileName(`/media/${name}`)).toEqual({ title, episode })
  })

  it('joins title, episode and container with middle dots', () => {
    const line = identityLine(withSource('/m/The.Sopranos.S03E02.Proshai.Livushka.mkv'))
    expect(line).toBe('The Sopranos · S03E02 · MKV')
  })

  it('leaves the episode out for a film, and takes the container from the output name', () => {
    expect(identityLine(withSource('C:\\Films\\Heat (1995).mkv', { path: '/out/Heat.mp4' }))).toBe(
      'Heat (1995) · MP4',
    )
  })
})
