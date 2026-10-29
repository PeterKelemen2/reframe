import { describe, expect, it } from 'vitest'

import { createAppI18n } from '@/i18n'

import { formatBitrate, formatBytes, formatRate, videoLine } from './format'
import { hdr10Source, multitrackSource } from './testing'

const t = createAppI18n().global.t as (key: string, named?: Record<string, unknown>) => string

describe('the video line', () => {
  it('names the codec, size, rate, HDR format and colour of an HDR10 source', () => {
    const video = hdr10Source().video![0]!
    expect(videoLine(video, t).join(' · ')).toBe(
      'HEVC Main 10 · 320×180 · 25 fps · HDR10 · BT.2020 PQ',
    )
  })

  it('leaves out the colour of a source that does not tag it', () => {
    const video = multitrackSource().video![0]!
    expect(videoLine(video, t).join(' · ')).toBe('H.264 Constrained Baseline · 320×180 · 25 fps')
  })

  it('shows an NTSC rate with three decimals and marks a variable rate', () => {
    const video = { ...multitrackSource().video![0]!, vfr: true }
    video.avg_frame_rate = { num: 24000, den: 1001 }
    expect(videoLine(video, t)).toContain('23.976 fps (variable)')
    expect(formatRate({ num: 30000, den: 1001 })).toBe('29.97')
    expect(formatRate({ num: 0, den: 1 })).toBeNull()
  })
})

describe('sizes and bitrates', () => {
  it('counts sizes in binary units', () => {
    expect(formatBytes(1023, t)).toBe('1023 B')
    expect(formatBytes(378_787, t)).toBe('370 KiB')
    expect(formatBytes(5 * 1024 ** 2, t)).toBe('5.0 MiB')
    expect(formatBytes(3.5 * 1024 ** 3, t)).toBe('3.50 GiB')
  })

  it('shows bitrates in kb/s below 1 Mb/s and in Mb/s above', () => {
    expect(formatBitrate(753_617, t)).toBe('754 kb/s')
    expect(formatBitrate(12_340_000, t)).toBe('12.3 Mb/s')
  })
})
