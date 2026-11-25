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
    const job = sampleJob()
    job.audio![2]!.metadata!.original = true
    const [, , commentary] = audioChips(job, multitrackSource(), DEFINITIONS)
    expect(commentary).toMatchObject({
      language: 'en',
      name: "Director's Commentary",
      flags: ['original'],
      roles: [{ role: 'commentary', evidence: 'flag' }],
    })
  })

  it('leave out a flag that a badge from that flag names, and keep it beside a guessed role', () => {
    const job = sampleJob()
    job.audio![2]!.metadata!.commentary = true
    const source = multitrackSource()
    expect(audioChips(job, source, DEFINITIONS)[2]?.flags).toEqual([])
    source.audio![2]!.roles = [{ role: 'commentary', evidence: 'title', detail: 'title' }]
    expect(audioChips(job, source, DEFINITIONS)[2]?.flags).toEqual(['commentary'])
  })
})

describe('a track written with another codec, layout or name than its source', () => {
  it('names the source codec and layout it is made from', () => {
    const [japanese, english] = audioChips(sampleJob(), multitrackSource(), DEFINITIONS)
    // AC-3 5.1 → AAC Stereo; AAC-LC stereo → AAC stereo is the same codec and layout.
    expect(japanese).toMatchObject({ from: 'AC-3 5.1', encoder: 'AAC', layout: 'Stereo' })
    expect(english).toMatchObject({ from: null, encoder: 'AAC', layout: 'Stereo' })
  })

  it('names the source title of a renamed track', () => {
    const job = sampleJob()
    job.audio![0]!.metadata!.name = 'Japanese 2.0'
    job.subtitles![0]!.metadata!.name = 'English (full)'
    const [japanese, english] = audioChips(job, multitrackSource(), DEFINITIONS)
    expect(japanese).toMatchObject({ name: 'Japanese 2.0', sourceName: 'Japanese 5.1' })
    expect(english).toMatchObject({ name: 'English Stereo', sourceName: null })
    expect(subtitleChips(job, multitrackSource())[0]).toMatchObject({
      name: 'English (full)',
      sourceName: 'English',
    })
  })

  it('keeps the source layout where a mixdown would upmix', () => {
    const job = sampleJob()
    job.audio![1]!.mixdown = '5.1'
    expect(audioChips(job, multitrackSource(), DEFINITIONS)[1]).toMatchObject({
      layout: 'stereo',
      from: null,
    })
  })

  it('shows a passthru track that the container cannot hold as encoded by its fallback', () => {
    const definitions = sampleDefinitions()
    definitions.containers!.mkv!.audio = { copy: ['ac3'], encode: ['aac', 'ac3'] }
    const job = sampleJob()
    job.audio![0]!.action = 'passthru'
    job.audio![1]!.action = 'passthru'
    job.audio![1]!.encoder = null
    const [copied, fallback] = audioChips(job, multitrackSource(), definitions)
    expect(copied).toMatchObject({ passthru: true, encoder: null, from: null })
    expect(fallback).toMatchObject({ passthru: false, encoder: 'AAC', from: null })
  })

  it('shows the format a container converts a copied text subtitle to', () => {
    const definitions = sampleDefinitions()
    definitions.containers!.mp4 = {
      ...definitions.containers!.mp4!,
      subtitles: { copy: ['mov_text'], encode: ['mov_text'] },
      text_subtitle_target: 'mov_text',
    }
    const job = sampleJob()
    job.output!.container = 'mp4'
    expect(subtitleChips(job, multitrackSource(), undefined, definitions)[0]).toMatchObject({
      action: 'copy',
      convertTo: 'mov_text',
    })
    job.output!.container = 'mkv'
    expect(subtitleChips(job, multitrackSource(), undefined, definitions)[0]?.convertTo).toBe(null)
  })
})

describe('the names of the track chips', () => {
  it('are the names the server filled in, when they are for these tracks', () => {
    const job = sampleJob()
    job.audio![0]!.metadata!.name = '{lang_name} {codec}'
    const source = multitrackSource()
    const written = ['Japanese AC-3', null, "Director's Commentary"]
    expect(audioChips(job, source, DEFINITIONS, written).map((chip) => chip.name)).toEqual([
      'Japanese AC-3',
      'English Stereo',
      "Director's Commentary",
    ])
    expect(audioChips(job, source, DEFINITIONS, ['stale'])[0]?.name).toBe('{lang_name} {codec}')
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

  it('leave out the forced and hearing-impaired flags that their badges name', () => {
    const job = sampleJob()
    job.subtitles = [
      {
        ...job.subtitles![0]!,
        source: 5,
        metadata: { ...job.subtitles![0]!.metadata!, default: false, hearing_impaired: true },
      },
      {
        ...job.subtitles![0]!,
        source: 6,
        metadata: { ...job.subtitles![0]!.metadata!, default: true, forced: true },
      },
    ]
    const [sdh, forced] = subtitleChips(job, multitrackSource())
    expect(sdh).toMatchObject({ roles: [{ role: 'sdh' }], flags: [] })
    expect(forced).toMatchObject({
      roles: [{ role: 'forced' }, { role: 'signs' }],
      flags: ['default'],
    })
  })
})
