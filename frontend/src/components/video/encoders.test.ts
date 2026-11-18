import { describe, expect, it } from 'vitest'

import type { EncoderStatus, JsonPatchOp } from '@/api/types'
import { sampleJob } from '@/editor/testing/samples'

import {
  availabilityOf,
  bandFor,
  bitDepthOps,
  convertQuality,
  groupEncoders,
  roundToStep,
  switchEncoderOps,
  type VideoEncoderDef,
  type VideoSettings,
} from './encoders'
import { encoderDefs, snapshot, videoOf, withStatus } from './testing'

const defs = encoderDefs()

function def(id: string): VideoEncoderDef {
  return defs[id] as VideoEncoderDef
}

function quality(id: string) {
  return def(id).rate_control?.quality as NonNullable<
    NonNullable<VideoEncoderDef['rate_control']>['quality']
  >
}

function video(changes: Partial<VideoSettings> = {}): VideoSettings {
  return { ...videoOf(sampleJob()), ...changes }
}

function status(state: EncoderStatus['state'], extra: Partial<EncoderStatus> = {}): EncoderStatus {
  return {
    id: 'x',
    state,
    hardware: true,
    in_build: true,
    reason: 'why',
    build_mismatch: false,
    ...extra,
  }
}

function paths(ops: JsonPatchOp[]): Record<string, unknown> {
  return Object.fromEntries(ops.map((op) => [op.path, 'value' in op ? op.value : op.op]))
}

describe('groupEncoders', () => {
  it('puts the families in the picker order and keeps the definitions order inside one', () => {
    const shuffled = Object.fromEntries(
      ['hevc_vaapi', 'hevc_amf', 'libx265', 'hevc_nvenc', 'libx264', 'hevc_qsv'].map((id) => [
        id,
        def(id),
      ]),
    )
    expect(
      groupEncoders(shuffled).map((group) => [group.family, group.encoders.map((e) => e.id)]),
    ).toEqual([
      ['software', ['libx265', 'libx264']],
      ['nvenc', ['hevc_nvenc']],
      ['qsv', ['hevc_qsv']],
      ['amf', ['hevc_amf']],
      ['vaapi', ['hevc_vaapi']],
    ])
  })
})

describe('availabilityOf', () => {
  const settled = snapshot()

  it('lets an available encoder be chosen', () => {
    expect(availabilityOf(status('available'), settled)).toMatchObject({
      kind: 'available',
      tone: 'ok',
      selectable: true,
    })
  })

  it('shows an encoder being detected as checking, and lets it be chosen', () => {
    expect(availabilityOf(status('checking'), settled)).toMatchObject({
      kind: 'checking',
      tone: 'busy',
      selectable: true,
    })
  })

  it('shows checking before the encoder list was read, or before any snapshot', () => {
    expect(availabilityOf(status('unknown', { in_build: null }), settled).kind).toBe('checking')
    expect(availabilityOf(undefined, null).kind).toBe('checking')
    expect(availabilityOf(undefined, snapshot({ detecting: true })).kind).toBe('checking')
  })

  it('shows an encoder that a finished snapshot does not list as unknown', () => {
    expect(availabilityOf(undefined, settled)).toMatchObject({ kind: 'unknown', selectable: true })
  })

  it('shows an encoder that was not tested with its reason, and lets it be chosen', () => {
    expect(availabilityOf(status('unknown', { reason: 'Not tested: off' }), settled)).toEqual({
      kind: 'untested',
      tone: 'off',
      selectable: true,
      reason: 'Not tested: off',
    })
  })

  it('refuses an unavailable encoder and keeps its reason', () => {
    expect(availabilityOf(status('unavailable', { reason: 'No driver' }), settled)).toEqual({
      kind: 'unavailable',
      tone: 'error',
      selectable: false,
      reason: 'No driver',
    })
  })

  it('refuses an encoder whose check failed', () => {
    expect(availabilityOf(status('error'), settled)).toMatchObject({
      kind: 'failed',
      selectable: false,
    })
  })

  it('lets a cached failure that detection checks again be chosen', () => {
    const rechecking = snapshot({ from_cache: true, detecting: true })
    expect(availabilityOf(status('unavailable'), rechecking)).toMatchObject({
      kind: 'rechecking',
      tone: 'busy',
      selectable: true,
      reason: 'why',
    })
  })
})

describe('quality scales', () => {
  // The server's closest-match fixes on the real server: "quality CQ 22 → CQ 20" (an x265 job
  // set to hevc_nvenc, to hevc_amf) and "CQ 27 → CQ 25" (the H.265 NVENC preset, to hevc_amf).
  it('converts as the server does', () => {
    expect(convertQuality(22, quality('hevc_nvenc'), quality('hevc_amf'))).toBe(20)
    expect(convertQuality(27, quality('hevc_nvenc'), quality('hevc_amf'))).toBe(25)
  })

  it('clamps to the scale and rounds to its step, halves up', () => {
    const mode = { min: 1, max: 51, step: 0.1 }
    expect(roundToStep(60, mode)).toBe(51)
    expect(roundToStep(-3, mode)).toBe(1)
    expect(roundToStep(22.25, mode)).toBe(22.3)
    expect(roundToStep(22.5, { min: 0, max: 51, step: 1 })).toBe(23)
  })
})

describe('bandFor', () => {
  const x265 = quality('libx265')

  it('takes the first band that holds the picture, the last one above all', () => {
    expect(bandFor(x265, 180)).toMatchObject({ max_height: 576, low: 18, high: 22 })
    expect(bandFor(x265, 1080)).toMatchObject({ max_height: 1080, low: 20, high: 24 })
    expect(bandFor(x265, 1081)).toMatchObject({ max_height: 2160 })
    expect(bandFor(x265, 4320)).toMatchObject({ max_height: 2160 })
  })

  it('has no band without a size or without bands', () => {
    expect(bandFor(x265, null)).toBeNull()
    expect(bandFor(quality('hevc_nvenc'), 1080)).toBeNull()
  })
})

describe('switchEncoderOps', () => {
  it('converts the quality, resets what the new encoder lacks and clears the custom parameters', () => {
    const ops = switchEncoderOps(video(), 'hevc_nvenc', defs, snapshot())
    expect(ops).toEqual([
      { op: 'replace', path: '/video/encoder', value: 'hevc_nvenc' },
      {
        op: 'replace',
        path: '/video/rate_control/value',
        value: convertQuality(22, quality('libx265'), quality('hevc_nvenc')),
      },
      { op: 'replace', path: '/video/preset', value: null },
      { op: 'replace', path: '/video/custom_params', value: '' },
    ])
  })

  it('keeps a quality that needs no conversion and the choices the new encoder has', () => {
    const ops = switchEncoderOps(
      video({ custom_params: '', preset: 'medium', tune: 'grain' }),
      'libx264',
      defs,
      snapshot(),
    )
    expect(ops).toEqual([
      { op: 'replace', path: '/video/encoder', value: 'libx264' },
      { op: 'replace', path: '/video/profile', value: null },
    ])
  })

  it('turns 10-bit off for an encoder without it, and resets a 10-bit profile once', () => {
    // Not tested for 10-bit: only the definition says it has no 10-bit mode.
    const caps = withStatus(snapshot(), 'h264_amf', { supports_10bit: null })
    const ops = switchEncoderOps(video({ custom_params: '' }), 'h264_amf', defs, caps)
    expect(paths(ops)).toMatchObject({ '/video/bit_depth': 8, '/video/profile': null })
    expect(ops.filter((op) => op.path === '/video/profile')).toHaveLength(1)
  })

  it('turns 10-bit off when the 10-bit test of the new encoder failed', () => {
    const caps = withStatus(snapshot(), 'hevc_amf', { supports_10bit: false })
    const ops = switchEncoderOps(video({ custom_params: '' }), 'hevc_amf', defs, caps)
    // hevc_amf has main10, but only for 10-bit.
    expect(paths(ops)).toMatchObject({ '/video/bit_depth': 8, '/video/profile': null })
  })

  it('clamps the bitrate and turns 2-pass off for an encoder without it', () => {
    const rc = { mode: 'bitrate', kbps: 50, two_pass: true, turbo_first_pass: true } as const
    const ops = switchEncoderOps(video({ rate_control: rc }), 'hevc_amf', defs, snapshot())
    expect(paths(ops)).toMatchObject({
      '/video/rate_control/kbps': 100,
      '/video/rate_control/two_pass': false,
      '/video/rate_control/turbo_first_pass': false,
    })
  })

  it('switches to the other rate control when the new encoder lacks the current one', () => {
    const noQuality = { ...def('libx264'), id: 'bitrate_only' } as VideoEncoderDef
    noQuality.rate_control = { ...noQuality.rate_control, quality: null }
    const noBitrate = { ...def('libx264'), id: 'quality_only' } as VideoEncoderDef
    noBitrate.rate_control = { ...noBitrate.rate_control, bitrate: null }
    const all = { ...defs, bitrate_only: noQuality, quality_only: noBitrate }

    expect(
      paths(switchEncoderOps(video(), 'bitrate_only', all, null))['/video/rate_control'],
    ).toEqual({ mode: 'bitrate', kbps: 6000, two_pass: false, turbo_first_pass: false })
    const rc = { mode: 'bitrate', kbps: 3000, two_pass: false, turbo_first_pass: false } as const
    expect(
      paths(switchEncoderOps(video({ rate_control: rc }), 'quality_only', all, null))[
        '/video/rate_control'
      ],
    ).toEqual({ mode: 'quality', value: 22 })
  })

  it('turns fast decode off for an encoder without it', () => {
    const ops = switchEncoderOps(video({ fast_decode: true }), 'hevc_amf', defs, snapshot())
    expect(paths(ops)['/video/fast_decode']).toBe(false)
  })

  it('keeps only the advanced options the new encoder has, with a value that fits', () => {
    const advanced = { 'rc-lookahead': 10, bframes: 99, unknown: 1 }
    const ops = switchEncoderOps(
      video({ encoder: 'hevc_nvenc', advanced, custom_params: '' }),
      'libx265',
      defs,
      snapshot(),
    )
    expect(paths(ops)['/video/advanced']).toEqual({ 'rc-lookahead': 10 })
  })

  it('adds a member the job does not have instead of replacing it', () => {
    const older = video({ custom_params: '' }) as Partial<VideoSettings>
    delete older.rate_control
    const ops = switchEncoderOps(older as VideoSettings, 'hevc_amf', defs, snapshot())
    expect(ops).toContainEqual({
      op: 'add',
      path: '/video/rate_control',
      value: { mode: 'quality', value: 25 },
    })
  })
})

describe('bitDepthOps', () => {
  it('resets a profile that does not allow the new depth', () => {
    expect(bitDepthOps(video(), def('libx265'), 8)).toEqual([
      { op: 'replace', path: '/video/bit_depth', value: 8 },
      { op: 'replace', path: '/video/profile', value: null },
    ])
  })

  it('keeps a profile that allows it', () => {
    expect(bitDepthOps(video({ bit_depth: 8, profile: 'main10' }), def('libx265'), 10)).toEqual([
      { op: 'replace', path: '/video/bit_depth', value: 10 },
    ])
  })
})
