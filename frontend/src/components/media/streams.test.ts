import { describe, expect, it } from 'vitest'

import type { AudioStream, SubtitleStream } from '@/api/types'
import { formatters } from '@/components/summary/testing'
import { probedSource } from '@/components/tracks/testing'

import {
  channelsText,
  delayText,
  kiloHertz,
  oneDecimal,
  preciseDuration,
  setDispositions,
  shownFlags,
  streamLabel,
} from './streams'

const multitrack = probedSource('multitrack')
const [japanese, english, commentary] = multitrack.audio as [AudioStream, AudioStream, AudioStream]
const signs = multitrack.subtitles![2] as SubtitleStream
const dts = probedSource('dts-hd-ma').audio![0] as AudioStream

describe('the flags beside the role badges', () => {
  it('leaves out a flag that a badge from that flag already names', () => {
    expect(shownFlags(commentary)).toEqual([])
    expect(shownFlags(signs)).toEqual([])
  })

  it('keeps a flag that no badge names', () => {
    expect(shownFlags(japanese)).toEqual(['default'])
  })

  it('keeps the flag when the badge comes from the title', () => {
    const titled = {
      ...commentary,
      roles: [{ role: 'commentary', evidence: 'title', detail: null }],
    } as AudioStream
    expect(shownFlags(titled)).toEqual(['comment'])
  })

  it('lists every disposition that is set for the details', () => {
    const covered = { ...japanese, disposition: { ...japanese.disposition!, attached_pic: true } }
    expect(setDispositions(covered)).toEqual(['default', 'attached_pic'])
    expect(setDispositions(english)).toEqual([])
  })
})

describe('channels', () => {
  it('names the layout without its variant', () => {
    expect(channelsText(japanese)).toBe('5.1')
    expect(channelsText(english)).toBe('2.0')
  })

  it('counts the channels of a layout without a common name', () => {
    expect(channelsText({ ...english, channel_layout: 'hexagonal', channels: 6 })).toBe('6')
  })

  it('is unknown without a layout or a count', () => {
    expect(channelsText({ ...english, channel_layout: null, channels: 0 })).toBeNull()
  })
})

describe('the label of a source choice', () => {
  it('is number, language, codec with channels, and title', () => {
    expect(streamLabel(dts)).toBe('1 · hun · DTS-HD MA 5.1 · DTS-HD MA 5.1')
    expect(streamLabel(signs)).toBe('3 · eng · SRT · Signs & Songs')
  })

  it('names an untagged track und and leaves out a missing title', () => {
    expect(streamLabel({ ...english, language: null, title: null })).toBe('2 · und · AAC-LC 2.0')
  })

  it('prefers the BCP 47 tag', () => {
    expect(streamLabel({ ...english, language_ietf: 'en-GB' })).toMatch(/^2 · en-GB ·/)
  })
})

describe('times', () => {
  it('shows a delay in milliseconds, with its sign', () => {
    const { t, n } = formatters()
    expect(delayText(0, t, n)).toBe('0 ms')
    expect(delayText(0.2, t, n)).toBe('+200 ms')
    expect(delayText(-1.5, t, n)).toBe('−1500 ms')
    expect(delayText(12, t, n)).toBe('+12 s')
    expect(delayText(-12.5, t, n)).toBe('−12.5 s')
  })

  it("writes delays, rates and loudness in the app's locale", () => {
    const { t, n } = formatters('de')
    expect(delayText(-12.5, t, n)).toBe('−12,5 s')
    expect(kiloHertz(44_100, n)).toBe('44,1')
    expect(oneDecimal(-22.54, n)).toBe('−22,5')
    expect(oneDecimal(2, n)).toBe('2,0')
    expect(oneDecimal(-0.01, n)).toBe('0,0')
  })

  it('shows a duration to the millisecond', () => {
    expect(preciseDuration(4.021)).toBe('0:04.021')
    expect(preciseDuration(3723.25)).toBe('1:02:03.250')
  })
})
