import { describe, expect, it } from 'vitest'

import type { CapabilitySnapshot, Definitions, EncoderStatus } from '@/api/types'

import { encoderRows, vaapiNodes } from './encoders'

function status(id: string, extra: Partial<EncoderStatus> = {}): EncoderStatus {
  return { id, state: 'available', hardware: false, in_build: true, ...extra } as EncoderStatus
}

const definitions = {
  video_encoders: {
    libx265: { id: 'libx265', label: 'x265', family: 'software' },
    hevc_vaapi: { id: 'hevc_vaapi', label: 'VAAPI H.265', family: 'vaapi' },
    h264_vaapi: { id: 'h264_vaapi', label: 'VAAPI H.264', family: 'vaapi' },
  },
  audio_encoders: { aac: { id: 'aac', label: 'AAC' } },
} as unknown as Definitions

function snapshot(encoders: EncoderStatus[]): CapabilitySnapshot {
  return {
    encoders: Object.fromEntries(encoders.map((entry) => [entry.id, entry])),
    detecting: false,
    from_cache: false,
  } as CapabilitySnapshot
}

describe('encoderRows', () => {
  it('lists the video encoders, then the audio ones, then encoders only the server knows', () => {
    const rows = encoderRows(
      definitions,
      snapshot([status('aac'), status('libfdk_aac'), status('libx265')]),
    )
    expect(rows.map((row) => [row.id, row.kind])).toEqual([
      ['libx265', 'software'],
      ['hevc_vaapi', 'vaapi'],
      ['h264_vaapi', 'vaapi'],
      ['aac', 'audio'],
      ['libfdk_aac', null],
    ])
  })

  it('gives each row its availability, reason, check time and device', () => {
    const [row] = encoderRows(
      definitions,
      snapshot([
        status('libx265', {
          state: 'unavailable',
          reason: 'Not in this FFmpeg build',
          checked_at: '2026-10-29T20:00:00Z',
        }),
      ]),
    )
    expect(row?.availability).toMatchObject({
      kind: 'unavailable',
      reason: 'Not in this FFmpeg build',
    })
    expect(row?.checkedAt).toBe('2026-10-29T20:00:00Z')
    const vaapi = encoderRows(
      definitions,
      snapshot([status('hevc_vaapi', { device: '/dev/dri/renderD128' })]),
    ).find((entry) => entry.id === 'hevc_vaapi')
    expect(vaapi?.device).toBe('/dev/dri/renderD128')
  })
})

describe('vaapiNodes', () => {
  it('names each render node a VAAPI encoder works on once, in number order, with the saved one', () => {
    const rows = encoderRows(
      definitions,
      snapshot([
        status('hevc_vaapi', { device: '/dev/dri/renderD129' }),
        status('h264_vaapi', { device: '/dev/dri/renderD128' }),
        status('libx265', { device: '/dev/dri/renderD200' }),
      ]),
    )
    expect(vaapiNodes(rows, null)).toEqual(['/dev/dri/renderD128', '/dev/dri/renderD129'])
    expect(vaapiNodes(rows, '/dev/dri/renderD1000')).toEqual([
      '/dev/dri/renderD128',
      '/dev/dri/renderD129',
      '/dev/dri/renderD1000',
    ])
  })
})
