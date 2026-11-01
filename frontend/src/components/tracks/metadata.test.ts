import { describe, expect, it } from 'vitest'

import type { AudioOutputTrack, AudioStream, ExternalSubtitle, TrackMetadata } from '@/api/types'
import { languages } from '@/components/language/testing'
import { sampleJob } from '@/editor/testing/samples'

import {
  audioNameValues,
  bulkOps,
  EMPTY_METADATA,
  externalTrack,
  fromFileName,
  metadataOps,
  NAME_TEMPLATES,
  nameSuggestions,
} from './metadata'
import { probedSource, trackDefinitions } from './testing'

const META: TrackMetadata = { ...EMPTY_METADATA, language: 'en', name: 'English', default: true }

function file(overrides: Partial<ExternalSubtitle> = {}): ExternalSubtitle {
  return { path: '/media/a.hu.srt', language: 'hu', name: null, offset_ms: 0, ...overrides }
}

function track(overrides: Partial<AudioOutputTrack>): AudioOutputTrack {
  return { ...sampleJob().audio![0]!, ...overrides }
}

describe('metadataOps', () => {
  it('writes only the members that change', () => {
    expect(metadataOps('/audio/1/metadata', META, { language: 'en', commentary: true })).toEqual([
      { op: 'add', path: '/audio/1/metadata/commentary', value: true },
    ])
  })

  it('adds the whole block when the track has none, so the other flags are written too', () => {
    expect(metadataOps('/video/metadata', undefined, { language: 'hu' })).toEqual([
      { op: 'add', path: '/video/metadata', value: { ...EMPTY_METADATA, language: 'hu' } },
    ])
  })

  it("keeps an external file's language, name and flags equal to the output's", () => {
    const ops = metadataOps(
      '/subtitles/2/metadata',
      { ...EMPTY_METADATA, language: 'hu' },
      { language: 'pt-BR', name: 'Brazilian', hearing_impaired: true },
      file({ flags: { ...EMPTY_METADATA } }),
    )
    expect(ops).toEqual([
      { op: 'add', path: '/subtitles/2/metadata/language', value: 'pt-BR' },
      { op: 'add', path: '/subtitles/2/metadata/name', value: 'Brazilian' },
      { op: 'add', path: '/subtitles/2/metadata/hearing_impaired', value: true },
      { op: 'add', path: '/subtitles/2/source/language', value: 'pt-BR' },
      { op: 'add', path: '/subtitles/2/source/name', value: 'Brazilian' },
      { op: 'add', path: '/subtitles/2/source/flags/hearing_impaired', value: true },
    ])
  })

  it('adds the flags of an external file that has none as a whole', () => {
    const ops = metadataOps('/subtitles/0/metadata', EMPTY_METADATA, { forced: true }, file())
    expect(ops.at(-1)).toEqual({
      op: 'add',
      path: '/subtitles/0/source/flags',
      value: {
        default: false,
        forced: true,
        commentary: false,
        hearing_impaired: false,
        visual_impaired: false,
        original: false,
      },
    })
  })
})

describe('bulkOps', () => {
  it('changes the chosen tracks only, each once', () => {
    const tracks = sampleJob().audio!
    const ops = bulkOps('audio', tracks, [2, 0, 2], { original: true, language: 'hu' })
    expect(ops.map((op) => op.path)).toEqual([
      '/audio/0/metadata/original',
      '/audio/0/metadata/language',
      '/audio/2/metadata/original',
      '/audio/2/metadata/language',
    ])
  })

  it('mirrors the change into an external subtitle file', () => {
    const job = sampleJob()
    const tracks = [...job.subtitles!, { ...job.subtitles![0]!, source: file() }]
    const ops = bulkOps('subtitles', tracks, [1], { language: 'de' })
    expect(ops.map((op) => op.path)).toEqual([
      '/subtitles/1/metadata/language',
      '/subtitles/1/source/language',
    ])
  })
})

describe('track names', () => {
  it('leaves out a template with an empty value, and a text given already', () => {
    const suggestions = nameSuggestions(NAME_TEMPLATES.other, {
      lang_name: 'Hungarian',
      lang_native: 'Hungarian',
      codec: undefined,
      title: 'Signs',
    })
    expect(suggestions).toEqual([
      { template: '{lang_name}', text: 'Hungarian' },
      { template: '{title}', text: 'Signs' },
    ])
  })

  const stream = probedSource('multitrack').audio![0]! as AudioStream
  const japanese = {
    tag: 'ja',
    iso639_1: 'ja',
    iso639_2b: 'jpn',
    iso639_2t: 'jpn',
    iso639_3: 'jpn',
    english_name: 'Japanese',
    native_name: '日本語',
    variant: false,
  }
  const context = { languages: [...languages(), japanese], definitions: trackDefinitions() }

  it("names an encoded track by its encoder and mixdown, in the track's language", () => {
    const values = audioNameValues(
      track({ action: 'encode', encoder: 'aac', mixdown: 'stereo', metadata: META }),
      stream,
      { ...context, copied: false },
    )
    expect(values).toMatchObject({ lang_name: 'English', channels: '2.0', codec: 'AAC' })
    expect(nameSuggestions(NAME_TEMPLATES.audio, values)[0]?.text).toBe('English 2.0 AAC')
  })

  it('names a copied track by the source codec and layout', () => {
    const values = audioNameValues(
      track({ action: 'passthru', mixdown: 'stereo', metadata: { ...META, language: null } }),
      stream,
      { ...context, copied: true },
    )
    expect(values).toMatchObject({
      lang_name: 'Japanese',
      lang_native: '日本語',
      channels: '5.1',
      codec: 'AC-3',
    })
  })
})

describe('external subtitle files', () => {
  it('reads the language and flags from the parts before the extension', () => {
    const list = languages()
    expect(fromFileName('/m/Film.2019.pt-BR.forced.srt', list)).toEqual({
      language: 'pt-BR',
      forced: true,
      hearing_impaired: false,
    })
    expect(fromFileName('/m/Film.hun.sdh.ass', list)).toMatchObject({
      language: 'hu',
      hearing_impaired: true,
    })
    // A word of the title is not a language code, however it reads.
    expect(fromFileName('/m/The.Hu.Story.srt', list).language).toBeNull()
  })

  it('starts a new track without an encoding, not default, as the name says', () => {
    const added = externalTrack({ path: '/m/Film.ger.forced.srt' }, languages())
    expect(added.source).toMatchObject({ charset: null, offset_ms: 0, language: 'de' })
    expect(added.metadata).toMatchObject({ language: 'de', forced: true, default: false })
    expect(added.action).toBe('copy')
  })
})
