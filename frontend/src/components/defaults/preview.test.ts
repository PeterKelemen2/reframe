import { describe, expect, it } from 'vitest'

import type { AudioOutputTrack, SubtitleOutputTrack, TrackDecision, TrackDraft } from '@/api/types'
import { probedSource, trackDefinitions } from '@/components/tracks/testing'
import { createAppI18n } from '@/i18n'

import { inOutputOrder, outputLines } from './preview'

const i18n = createAppI18n().global
const t = i18n.t as (key: string, named?: Record<string, unknown>) => string
const n = (value: number) => i18n.n(value)
const definitions = trackDefinitions()
const dtsHdMa = probedSource('dts-hd-ma').audio![0]!

function audio(output: Partial<AudioOutputTrack>): AudioOutputTrack {
  return {
    action: 'encode',
    encoder: 'ac3',
    mixdown: '5.1',
    bitrate: 320,
    gain: 0,
    drc: 0,
    loudness: 'off',
    source_stream: 1,
    ...output,
  }
}

function decision(overrides: Partial<TrackDecision>): TrackDecision {
  return {
    source_stream: 1,
    kind: 'audio',
    selected: true,
    reason: 'why',
    measure: false,
    ...overrides,
  }
}

function subtitle(output: object): string[] {
  return outputLines(
    decision({
      kind: 'subtitle',
      subtitle_outputs: [{ forced_only: false, source: 4, ...output } as never],
    }),
    undefined,
    definitions,
    t,
    n,
  )
}

describe('the output column of the preview', () => {
  it('names the encoder, the layout and the bitrate, then each extra output', () => {
    const lines = outputLines(
      decision({
        outputs: [audio({}), audio({ encoder: 'aac', mixdown: 'stereo', bitrate: 160 })],
      }),
      dtsHdMa,
      definitions,
      t,
      n,
    )
    expect(lines).toEqual(['AC-3 5.1 · 320 kb/s', 'AAC Stereo · 160 kb/s'])
  })

  it('writes the bitrate with the locale’s digit grouping', () => {
    const lines = outputLines(
      decision({ outputs: [audio({ encoder: 'flac', mixdown: '7.1', bitrate: 1536 })] }),
      dtsHdMa,
      definitions,
      t,
      n,
    )
    expect(lines).toEqual(['FLAC 7.1 · 1,536 kb/s'])
  })

  it('names a lossless output without a bitrate, and a kept layout without a mixdown', () => {
    expect(
      outputLines(
        decision({ outputs: [audio({ encoder: 'flac', mixdown: null, bitrate: null })] }),
        dtsHdMa,
        definitions,
        t,
        n,
      ),
    ).toEqual(['FLAC'])
  })

  it("names a passthru output by the source track's codec", () => {
    expect(
      outputLines(
        decision({ outputs: [audio({ action: 'passthru', encoder: 'aac', mixdown: null })] }),
        dtsHdMa,
        definitions,
        t,
        n,
      ),
    ).toEqual(['Passthru (DTS-HD MA)'])
  })

  it('names what happens to a subtitle', () => {
    expect(subtitle({ action: 'copy' })).toEqual(['Copy'])
    expect(subtitle({ action: 'burn' })).toEqual(['Burn in'])
    expect(subtitle({ action: 'burn', forced_only: true })).toEqual(['Burn in (forced only)'])
    expect(subtitle({ action: 'convert', convert_to: 'srt' })).toEqual(['Convert to SRT'])
  })
})

describe('the order of the preview rows', () => {
  it('lists the tracks as they are written, then the dropped ones in source order', () => {
    // Source: 1 hun, 2 eng, 3 commentary (dropped), 4 jpn; the language list is eng, hun, jpn.
    const draft = {
      audio: [
        audio({ source_stream: 2 }),
        audio({ source_stream: 1 }),
        audio({ source_stream: 4 }),
      ],
      subtitles: [],
      decisions: [1, 2, 3, 4].map((stream) =>
        decision({ source_stream: stream, selected: stream !== 3 }),
      ),
      subtitle_decisions: [],
      issues: [],
    } satisfies TrackDraft
    expect(inOutputOrder(draft, 'audio').map((each) => each.source_stream)).toEqual([2, 1, 4, 3])
  })

  it('puts an extra output and an external subtitle where their first track is', () => {
    const external = { forced_only: false, source: { path: '/media/A.en.srt' } }
    const draft = {
      audio: [],
      subtitles: [
        { forced_only: false, source: 6 },
        external,
        { forced_only: false, source: 4 },
        { forced_only: true, source: 6 },
      ] as SubtitleOutputTrack[],
      decisions: [],
      subtitle_decisions: [3, 4, 5, 6].map((stream) =>
        decision({ kind: 'subtitle', source_stream: stream, selected: stream !== 5 }),
      ),
      issues: [],
    } satisfies TrackDraft
    expect(inOutputOrder(draft, 'subtitle').map((each) => each.source_stream)).toEqual([6, 4, 3, 5])
  })
})
