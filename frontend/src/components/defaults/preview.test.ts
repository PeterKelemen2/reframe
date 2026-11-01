import { describe, expect, it } from 'vitest'

import type { AudioOutputTrack, TrackDecision } from '@/api/types'
import { probedSource, trackDefinitions } from '@/components/tracks/testing'
import { createAppI18n } from '@/i18n'

import { outputLines } from './preview'

const t = createAppI18n().global.t as (key: string, named?: Record<string, unknown>) => string
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
  return { source_stream: 1, reason: 'why', ...overrides }
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
    )
    expect(lines).toEqual(['AC-3 5.1 · 320 kb/s', 'AAC Stereo · 160 kb/s'])
  })

  it('names a lossless output without a bitrate, and a kept layout without a mixdown', () => {
    expect(
      outputLines(
        decision({ outputs: [audio({ encoder: 'flac', mixdown: null, bitrate: null })] }),
        dtsHdMa,
        definitions,
        t,
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
      ),
    ).toEqual(['Passthru (DTS-HD MA)'])
  })

  it('names what happens to a subtitle', () => {
    const subtitle = (output: object) =>
      outputLines(
        decision({
          kind: 'subtitle',
          subtitle_outputs: [{ forced_only: false, source: 4, ...output } as never],
        }),
        undefined,
        definitions,
        t,
      )
    expect(subtitle({ action: 'copy' })).toEqual(['Copy'])
    expect(subtitle({ action: 'burn' })).toEqual(['Burn in'])
    expect(subtitle({ action: 'burn', forced_only: true })).toEqual(['Burn in (forced only)'])
    expect(subtitle({ action: 'convert', convert_to: 'srt' })).toEqual(['Convert to SRT'])
  })

  it('is empty for a dropped track', () => {
    expect(outputLines(decision({ selected: false }), dtsHdMa, definitions, t)).toEqual([])
  })
})
