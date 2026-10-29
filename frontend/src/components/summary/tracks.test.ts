import { describe, expect, it } from 'vitest'

import { sampleJob } from '@/editor/testing/samples'

import { multitrackSource, sampleDefinitions } from './testing'
import { audioChips, subtitleChips } from './tracks'

const DEFINITIONS = sampleDefinitions()

describe('the audio track chips', () => {
  it("show the encoder and mixdown of an encoded track and the source's codec and layout of a copied one", () => {
    const job = sampleJob()
    job.audio![0]!.action = 'passthru'
    job.audio![1]!.mixdown = null
    const [copied, kept, encoded] = audioChips(job, multitrackSource(), DEFINITIONS)
    expect(copied).toMatchObject({
      path: 'audio[0]',
      passthru: true,
      encoder: null,
      layout: '5.1(side)',
      stream: { display_codec: 'AC-3' },
    })
    expect(kept).toMatchObject({ path: 'audio[1]', encoder: 'AAC', layout: 'stereo' })
    expect(encoded).toMatchObject({ path: 'audio[2]', encoder: 'AAC', layout: 'Stereo' })
  })

  it("carry the output's language and flags and the source's roles", () => {
    const [, , commentary] = audioChips(sampleJob(), multitrackSource(), DEFINITIONS)
    expect(commentary).toMatchObject({
      language: 'en',
      name: "Director's Commentary",
      flags: ['commentary'],
      roles: [{ role: 'commentary', evidence: 'flag' }],
    })
  })
})

describe('the subtitle track chips', () => {
  it('show a converted format, a burned-in track and an external file', () => {
    const job = sampleJob()
    job.subtitles = [
      { ...job.subtitles![0]!, action: 'convert', convert_to: 'webvtt' },
      { ...job.subtitles![0]!, action: 'burn', source: 6 },
      {
        ...job.subtitles![0]!,
        source: { path: '/media/subs/movie.hu.srt', language: 'hu', offset_ms: 0 },
        metadata: undefined,
      },
    ]
    const [converted, burned, external] = subtitleChips(job, multitrackSource())
    expect(converted).toMatchObject({
      path: 'subtitles[0]',
      convertTo: 'WebVTT',
      flags: ['default'],
    })
    expect(burned).toMatchObject({
      path: 'subtitles[1]',
      action: 'burn',
      stream: { title: 'Signs & Songs' },
      roles: [{ role: 'forced' }, { role: 'signs' }],
    })
    expect(external).toMatchObject({ external: 'movie.hu.srt', language: 'hu', stream: undefined })
  })
})
