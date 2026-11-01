import { describe, expect, it } from 'vitest'

import type { AudioOutputTrack, AudioStream, JobDraft, SubtitleOutputTrack } from '@/api/types'
import { sampleJob } from '@/editor/testing/samples'

import {
  addOps,
  bitrateChoices,
  bitrateTable,
  canCopy,
  encoderChangeOps,
  followSelection,
  mixdownChangeOps,
  newAudioTrack,
  type NewTrackContext,
  newSubtitleTrack,
  rateModeOps,
  sourceChangeOps,
  subtitleActionOps,
  unusedStreams,
} from './ops'
import { probedSource, trackDefinitions } from './testing'

const definitions = trackDefinitions()
const multitrack = probedSource('multitrack')
const [japanese, english, commentary] = multitrack.audio as [AudioStream, AudioStream, AudioStream]
const subtitles = multitrack.subtitles ?? []

function context(overrides: Partial<NewTrackContext> = {}): NewTrackContext {
  return { definitions, container: 'mkv', draft: null, usable: () => true, ...overrides }
}

function audioTrack(overrides: Partial<AudioOutputTrack> = {}): AudioOutputTrack {
  return { ...sampleJob().audio![0]!, ...overrides } as AudioOutputTrack
}

describe('canCopy', () => {
  it('takes any codec under a wildcard except the listed exceptions', () => {
    const mkv = definitions.containers!.mkv!.audio
    expect(canCopy(mkv, 'dts')).toBe(true)
    expect(canCopy(mkv, 'pcm_bluray')).toBe(false)
  })

  it('takes only the listed codecs without a wildcard', () => {
    const mp4 = definitions.containers!.mp4!.subtitles
    expect(canCopy(mp4, 'mov_text')).toBe(true)
    expect(canCopy(mp4, 'hdmv_pgs_subtitle')).toBe(false)
  })
})

describe('a new audio track', () => {
  it("is the preset's own output for that source track when the draft has one", () => {
    const drafted = audioTrack({ action: 'passthru', encoder: 'ac3', source_stream: 1 })
    const draft = { decisions: [{ source_stream: 1, outputs: [drafted] }] } as unknown as JobDraft
    expect(newAudioTrack(japanese, [], context({ draft }))).toEqual(drafted)
  })

  it('is AAC stereo at its default bitrate, with the source flags, without a draft', () => {
    const track = newAudioTrack(commentary, [], context())
    expect(track).toMatchObject({
      action: 'encode',
      encoder: 'aac',
      mixdown: 'stereo',
      bitrate: 160,
      source_stream: 3,
      metadata: { commentary: true, default: false, language: null, name: null },
    })
  })

  it('stays mono for a mono source', () => {
    const mono = { ...english, channels: 1, channel_layout: 'mono' }
    expect(newAudioTrack(mono, [], context())).toMatchObject({ mixdown: 'mono', bitrate: 80 })
  })

  it('takes an encoder the container holds (Opus in WebM)', () => {
    expect(newAudioTrack(english, [], context({ container: 'webm' })).encoder).toBe('libopus')
  })

  it('passes over an encoder the build does not have', () => {
    const track = newAudioTrack(english, [], context({ usable: (id) => id !== 'aac' }))
    expect(track.encoder).toBe('libfdk_aac')
  })

  it('is not default beside a default track', () => {
    const existing = [audioTrack({ metadata: { ...audioTrack().metadata!, default: true } })]
    expect(newAudioTrack(japanese, existing, context()).metadata?.default).toBe(false)
    expect(newAudioTrack(japanese, [], context()).metadata?.default).toBe(true)
  })
})

describe('a new subtitle track', () => {
  it("is the preset's own output when the draft has one", () => {
    const drafted = { action: 'burn', convert_to: null, forced_only: true, source: 6 }
    const draft = {
      subtitle_decisions: [{ source_stream: 6, subtitle_outputs: [drafted] }],
    } as unknown as JobDraft
    expect(newSubtitleTrack(subtitles[2]!, [], { draft })).toEqual(drafted)
  })

  it('is a copy with the source flags without a draft', () => {
    expect(newSubtitleTrack(subtitles[1]!, [], { draft: null })).toMatchObject({
      action: 'copy',
      source: 5,
      metadata: { hearing_impaired: true, default: false },
    })
  })
})

describe('adding several tracks', () => {
  it('adds one track per stream, each seeing the ones before it', () => {
    const second = { ...english, disposition: { ...english.disposition!, default: true } }
    const ops = addOps<AudioOutputTrack, AudioStream>(
      'audio',
      [japanese, second],
      [],
      (stream, existing) => newAudioTrack(stream, existing, context()),
    )
    expect(ops.map((op) => op.path)).toEqual(['/audio/-', '/audio/-'])
    const added = ops.map((op) => (op as { value: AudioOutputTrack }).value)
    expect(added.map((track) => track.metadata?.default)).toEqual([true, false])
  })

  it('finds the source streams no output reads', () => {
    expect(unusedStreams(multitrack.audio!, [audioTrack({ source_stream: 2 })])).toEqual([
      japanese,
      commentary,
    ])
    const subtitle = { source: 5 } as SubtitleOutputTrack
    expect(unusedStreams(subtitles, [subtitle]).map((stream) => stream.index)).toEqual([4, 6])
  })
})

describe('another source stream', () => {
  it("takes the new stream's flags and keeps the track's default flag", () => {
    const track = audioTrack({ metadata: { ...audioTrack().metadata!, default: true } })
    expect(sourceChangeOps('audio', 0, track, commentary)).toEqual([
      { op: 'replace', path: '/audio/0/source_stream', value: 3 },
      {
        op: 'replace',
        path: '/audio/0/metadata',
        value: expect.objectContaining({ commentary: true, default: true, name: null }),
      },
    ])
  })

  it('writes the source member of a subtitle track', () => {
    const track = { action: 'copy', source: 4, forced_only: false } as SubtitleOutputTrack
    expect(sourceChangeOps('subtitles', 1, track, subtitles[2]!)[0]).toEqual({
      op: 'replace',
      path: '/subtitles/1/source',
      value: 6,
    })
  })
})

describe('another encoder', () => {
  it('keeps a bitrate the new encoder can write', () => {
    expect(encoderChangeOps(0, audioTrack(), 'ac3', definitions, 6)).toEqual([
      { op: 'replace', path: '/audio/0/encoder', value: 'ac3' },
    ])
  })

  it('moves a bitrate outside the range to the default of the layout', () => {
    const track = audioTrack({ bitrate: 1024 })
    expect(encoderChangeOps(0, track, 'libopus', definitions, 6)).toContainEqual({
      op: 'replace',
      path: '/audio/0/bitrate',
      value: 96,
    })
  })

  it('moves a bitrate the encoder does not list to the default', () => {
    const track = audioTrack({ bitrate: 150 })
    expect(encoderChangeOps(0, track, 'ac3', definitions, 6)).toContainEqual({
      op: 'replace',
      path: '/audio/0/bitrate',
      value: 224,
    })
  })

  it('changes a mixdown the encoder cannot make', () => {
    const track = audioTrack({ mixdown: '5.1', bitrate: 384 })
    expect(encoderChangeOps(0, track, 'libmp3lame', definitions, 6)).toEqual([
      { op: 'replace', path: '/audio/0/encoder', value: 'libmp3lame' },
      { op: 'replace', path: '/audio/0/mixdown', value: 'stereo' },
      { op: 'replace', path: '/audio/0/bitrate', value: 160 },
    ])
  })

  it('clears the bitrate for a lossless encoder and a quality the encoder lacks', () => {
    const track = audioTrack({ encoder: 'libmp3lame', bitrate: null, quality: 2 })
    expect(encoderChangeOps(0, track, 'flac', definitions, 2)).toEqual([
      { op: 'replace', path: '/audio/0/encoder', value: 'flac' },
      { op: 'replace', path: '/audio/0/quality', value: null },
    ])
    expect(encoderChangeOps(0, audioTrack(), 'flac', definitions, 2)).toContainEqual({
      op: 'replace',
      path: '/audio/0/bitrate',
      value: null,
    })
  })
})

describe('another mixdown', () => {
  it("moves a bitrate below the new layout's range to its default", () => {
    expect(mixdownChangeOps(0, audioTrack(), '5.1', definitions, 6)).toEqual([
      { op: 'replace', path: '/audio/0/mixdown', value: '5.1' },
      { op: 'replace', path: '/audio/0/bitrate', value: 384 },
    ])
  })

  it('keeps a bitrate inside the range', () => {
    expect(mixdownChangeOps(0, audioTrack(), 'mono', definitions, 6)).toEqual([
      { op: 'replace', path: '/audio/0/mixdown', value: 'mono' },
    ])
  })
})

describe('bitrate choices', () => {
  it("uses the source layout's table when the layout is kept", () => {
    const aac = definitions.audio_encoders!.aac
    expect(bitrateTable(aac, null, 6)?.default).toBe(384)
    expect(bitrateTable(aac, null, 1)?.default).toBe(80)
    expect(bitrateTable(definitions.audio_encoders!.ac3, null, 8)?.default).toBe(640)
  })

  it("offers the encoder's own list inside the range, and the track's value", () => {
    const ac3 = definitions.audio_encoders!.ac3
    const choices = bitrateChoices(ac3, bitrateTable(ac3, '5.1', 6), 150)
    expect(choices[0]).toBe(150)
    expect(choices.slice(1)).toEqual([224, 256, 320, 384, 448, 512, 576, 640])
  })
})

describe('bitrate or quality', () => {
  it("switches to the encoder's default quality, and back to the default bitrate", () => {
    const lame = definitions.audio_encoders!.libmp3lame
    expect(rateModeOps(1, 'quality', lame)).toEqual([
      { op: 'replace', path: '/audio/1/bitrate', value: null },
      { op: 'replace', path: '/audio/1/quality', value: 2 },
    ])
    expect(rateModeOps(1, 'bitrate', lame)).toEqual([
      { op: 'replace', path: '/audio/1/quality', value: null },
      { op: 'replace', path: '/audio/1/bitrate', value: null },
    ])
  })
})

describe('another subtitle action', () => {
  const copy = { action: 'copy', convert_to: null, forced_only: false, source: 4 } as const

  it("converts to the container's text format", () => {
    expect(subtitleActionOps(0, copy, 'convert', definitions.containers!.mp4)).toEqual([
      { op: 'replace', path: '/subtitles/0/action', value: 'convert' },
      { op: 'replace', path: '/subtitles/0/convert_to', value: 'mov_text' },
    ])
  })

  it('clears the format and forced-only that the new action does not use', () => {
    const converted = { ...copy, action: 'convert', convert_to: 'srt' } as const
    expect(subtitleActionOps(0, converted, 'burn', undefined)).toEqual([
      { op: 'replace', path: '/subtitles/0/action', value: 'burn' },
      { op: 'replace', path: '/subtitles/0/convert_to', value: null },
    ])
    const burned = { ...copy, action: 'burn', forced_only: true } as const
    expect(subtitleActionOps(0, burned, 'copy', undefined)).toEqual([
      { op: 'replace', path: '/subtitles/0/action', value: 'copy' },
      { op: 'replace', path: '/subtitles/0/forced_only', value: false },
    ])
  })
})

function named(track: AudioOutputTrack, name: string): AudioOutputTrack {
  return { ...track, metadata: { ...track.metadata!, name } }
}

function file(path: string, language: string | null): SubtitleOutputTrack {
  return {
    action: 'copy',
    convert_to: null,
    forced_only: false,
    source: { path, language, name: null, offset_ms: 0, charset: null },
    metadata: { ...audioTrack().metadata!, language },
  }
}

describe('the bulk selection through a change of the list', () => {
  const aac = audioTrack({ source_stream: 1, encoder: 'aac' })
  const ac3 = audioTrack({ source_stream: 1, encoder: 'ac3', bitrate: 192 })
  const other = audioTrack({ source_stream: 2 })

  it('follows a selected track that changes place with another output of its stream', () => {
    expect(followSelection([aac, ac3, other], [ac3, aac, other], [0])).toEqual([1])
  })

  it('keeps equal tracks in their order among themselves', () => {
    expect(followSelection([aac, aac, other], [aac, other, aac], [1])).toEqual([2])
  })

  it('keeps the places when the metadata of several tracks changes', () => {
    const after = [named(aac, 'A'), named(ac3, 'B'), other]
    expect(followSelection([aac, ac3, other], after, [0, 2])).toEqual([0, 2])
  })

  it('keeps the places when the language of several external files changes', () => {
    const before = [file('/a.srt', null), file('/b.srt', null)]
    const after = [file('/a.srt', 'hu'), file('/b.srt', 'hu')]
    expect(followSelection(before, after, [1])).toEqual([1])
  })

  it('keeps the places when the settings of one track change', () => {
    const after = [aac, { ...ac3, bitrate: 384 }, other]
    expect(followSelection([aac, ac3, other], after, [1])).toEqual([1])
  })

  it('clears it when the settings of several tracks change in one step', () => {
    const before = [named(aac, 'A'), named(ac3, 'B'), other]
    const after = [named(ac3, 'A'), named(aac, 'B'), other]
    expect(followSelection(before, after, [0])).toEqual([])
  })

  it('clears it when a track is added or removed', () => {
    expect(followSelection([aac, ac3, other], [aac, other], [0])).toEqual([])
  })
})
