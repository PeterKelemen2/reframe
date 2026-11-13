import { describe, expect, it } from 'vitest'

import type { MediaSource } from '@/api/types'
import { createAppI18n } from '@/i18n'

import {
  canUseFrames,
  convertRange,
  formatClock,
  formatTime,
  frameRate,
  hasChapters,
  parseFrame,
  parseTime,
  type Range,
  rangeLabel,
  rangeSeconds,
} from './range'
import { bareSource, chaptersSource } from './testing'

const { t } = createAppI18n().global

function seconds(range: Range, source = chaptersSource()): number | null {
  return rangeSeconds({ range }, source)
}

describe('parsing a typed time', () => {
  it.each([
    ['0:01:30.000', 90],
    ['1:02:03.5', 3723.5],
    ['01:30', 90],
    ['90:00', 5400],
    ['1:30.25', 90.25],
    ['90', 90],
    ['2.5', 2.5],
    ['.5', 0.5],
    ['  12  ', 12],
    ['0:00:01.0004', 1],
    ['1.0004', 1],
    ['1:30.0004', 90],
  ])('reads %s as %d seconds', (text, value) => {
    expect(parseTime(text)).toBe(value)
  })

  it.each(['', 'abc', '1:60', '1:2:60', '1:60:00', '-5', '1,5', '1:', ':30', '1:30:00:00', '1e3'])(
    'refuses %j',
    (text) => {
      expect(parseTime(text)).toBeNull()
    },
  )
})

describe('formatting a time', () => {
  it('gives H:MM:SS.mmm in the fields, to the millisecond', () => {
    expect(formatTime(90)).toBe('0:01:30.000')
    expect(formatTime(3723.5)).toBe('1:02:03.500')
    expect(formatTime(2.0004)).toBe('0:00:02.000')
    expect(formatTime(59.9996)).toBe('0:01:00.000')
  })

  it('leaves the milliseconds out of a label when there are none', () => {
    expect(formatClock(90)).toBe('0:01:30')
    expect(formatClock(2700)).toBe('0:45:00')
    expect(formatClock(2.5)).toBe('0:00:02.500')
  })

  it('reads back what it writes', () => {
    for (const value of [0, 1.001, 61.5, 3599.999, 36000]) {
      expect(parseTime(formatTime(value))).toBe(value)
    }
  })
})

describe('parsing a typed frame', () => {
  it('takes whole numbers from 0 only', () => {
    expect(parseFrame(' 1440 ')).toBe(1440)
    expect(parseFrame('0')).toBe(0)
    for (const text of ['', '1.5', '-1', 'x', '1e3']) expect(parseFrame(text)).toBeNull()
  })
})

describe('the seconds a range covers', () => {
  it('is the whole source, the chapters’ times, the time span or the frames at the frame rate', () => {
    expect(seconds({ kind: 'full' })).toBe(5.021)
    expect(seconds({ kind: 'chapters', start: 2, end: 3 })).toBe(3)
    expect(seconds({ kind: 'time', start: 1, end: 4 })).toBe(3)
    expect(seconds({ kind: 'time', start: 1, end: null })).toBeCloseTo(4.021)
    expect(seconds({ kind: 'frames', start: 25, end: 100 })).toBe(3)
  })

  it('stops at the end of the source, as the server clamps it', () => {
    expect(seconds({ kind: 'time', start: 4, end: 60 })).toBeCloseTo(1.021)
    expect(seconds({ kind: 'time', start: 10, end: 20 })).toBe(0)
    expect(seconds({ kind: 'chapters', start: 3, end: 9 })).toBe(2.5)
    // 5.021 s at 25 fps: 126 frames.
    expect(seconds({ kind: 'frames', start: 100, end: 1000 })).toBe(26 / 25)
    expect(seconds({ kind: 'frames', start: 100, end: null })).toBe(26 / 25)
  })

  it('is not known without the data', () => {
    expect(seconds({ kind: 'chapters', start: 5, end: 6 })).toBeNull()
    expect(seconds({ kind: 'chapters', start: 1, end: 1 }, bareSource())).toBeNull()
    expect(seconds({ kind: 'frames', start: 0, end: 25 }, bareSource())).toBeNull()
    const noDuration = chaptersSource()
    noDuration.container = { ...noDuration.container, duration: null }
    expect(seconds({ kind: 'full' }, noDuration)).toBeNull()
    expect(seconds({ kind: 'time', start: 1, end: null }, noDuration)).toBeNull()
    expect(seconds({ kind: 'time', start: 1, end: 3 }, noDuration)).toBe(2)
  })

  it('counts the frames from the stream’s frame count when it has one', () => {
    const source = chaptersSource()
    source.video![0]!.frame_count = 50
    expect(seconds({ kind: 'frames', start: 25, end: 100 }, source)).toBe(1)
  })

  it('takes the stream’s duration when the container has none', () => {
    const source = chaptersSource()
    source.container = { ...source.container, duration: null }
    source.video![0]!.duration = 2
    expect(seconds({ kind: 'time', start: 1, end: 60 }, source)).toBe(1)
  })
})

/**
 * A Blu-ray-like source at 24000/1001 fps, its chapter edges on frames, in ffprobe's whole µs:
 * frame 7490 rounds up (312.395417), frame 14 386 down (600.016083).
 */
function bluray(): MediaSource {
  const source = chaptersSource()
  source.container = { ...source.container, duration: 1800 }
  source.video = [{ ...source.video![0]!, avg_frame_rate: { num: 24000, den: 1001 } }]
  const fps = 24000 / 1001
  const edges = [0, 7490, 14_386, 30_000, 43_157].map((frame) => Number((frame / fps).toFixed(6)))
  source.chapters = edges.slice(0, -1).map((start, index) => ({
    index,
    start,
    end: edges[index + 1]!,
    title: `Chapter ${index + 1}`,
  }))
  return source
}

/** A phone video as `testdata/probes/vfr.json` gives it: no average frame rate, 120/1 r. */
function phone(): MediaSource {
  const source = chaptersSource()
  source.container = { ...source.container, duration: 3.021 }
  source.video = [
    {
      ...source.video![0]!,
      avg_frame_rate: null,
      frame_rate: { num: 120, den: 1 },
      frame_count: 114,
      duration: 2.983,
    },
  ]
  return source
}

describe('the frame rate', () => {
  it('is the average one, not the stream’s', () => {
    const source = chaptersSource()
    source.video![0]!.frame_rate = { num: 50, den: 1 }
    expect(frameRate(source)).toBe(25)
  })

  it('is frames ÷ duration without an average, as the command builder counts it', () => {
    // 114 / 2.983 s, not the 120/1 of the stream: the builder's 6000/157.
    expect(frameRate(phone())).toBe(6000 / 157)
    expect(seconds({ kind: 'frames', start: 0, end: 57 }, phone())).toBe(57 / (6000 / 157))
    expect(convertRange({ kind: 'time', start: 1, end: 2 }, 'frames', phone())).toEqual({
      kind: 'frames',
      start: 38,
      end: 77,
    })
  })

  it('snaps a counted rate to a standard one within 0.2 %', () => {
    const source = phone()
    // 1439 / 60.06 s is 23.9594 fps: 0.07 % from 24000/1001.
    source.video![0]!.frame_count = 1439
    source.video![0]!.duration = 60.06
    expect(frameRate(source)).toBe(24000 / 1001)
  })

  it('is the stream’s rate when nothing else says it', () => {
    const source = phone()
    source.video![0]!.frame_count = null
    expect(frameRate(source)).toBe(120)
    source.video![0]!.frame_rate = null
    expect(frameRate(source)).toBeNull()
  })
})

describe('the frames of a source without a frame count', () => {
  it('round duration × rate half to even, as the server does', () => {
    const source = chaptersSource()
    // 4.5 s × 25 = 112.5 frames: 112, so frames 0 – end last 112 / 25 s.
    source.container = { ...source.container, duration: 4.5 }
    expect(seconds({ kind: 'frames', start: 0, end: null }, source)).toBe(112 / 25)
    source.container = { ...source.container, duration: 4.54 }
    expect(seconds({ kind: 'frames', start: 0, end: null }, source)).toBe(114 / 25)
  })
})

describe('what the source can use', () => {
  it('needs chapters for chapters, and a frame rate (or a frame count and a duration) for frames', () => {
    expect(hasChapters(chaptersSource())).toBe(true)
    expect(hasChapters(bareSource())).toBe(false)
    expect(canUseFrames(chaptersSource())).toBe(true)
    expect(canUseFrames(bareSource())).toBe(false)
    const counted = bareSource()
    counted.video![0]!.frame_count = 125
    counted.video![0]!.duration = 5
    expect(canUseFrames(counted)).toBe(true)
    const rated = bareSource()
    rated.video![0]!.frame_rate = { num: 24000, den: 1001 }
    expect(canUseFrames(rated)).toBe(true)
    const audioOnly = chaptersSource()
    audioOnly.video = []
    expect(canUseFrames(audioOnly)).toBe(false)
  })
})

describe('changing the mode', () => {
  const source = chaptersSource()
  const chapters23: Range = { kind: 'chapters', start: 2, end: 3 }

  it('turns chapters into their times, and times into frames (start down, end up)', () => {
    const time = convertRange(chapters23, 'time', source)
    expect(time).toEqual({ kind: 'time', start: 1, end: 4 })
    expect(convertRange(time, 'frames', source)).toEqual({ kind: 'frames', start: 25, end: 100 })
    expect(convertRange({ kind: 'time', start: 1.03, end: 3.97 }, 'frames', source)).toEqual({
      kind: 'frames',
      start: 25,
      end: 100,
    })
    expect(convertRange(chapters23, 'frames', source)).toEqual({
      kind: 'frames',
      start: 25,
      end: 100,
    })
  })

  it('turns frames into seconds, and keeps an open end open', () => {
    expect(convertRange({ kind: 'frames', start: 25, end: 100 }, 'time', source)).toEqual({
      kind: 'time',
      start: 1,
      end: 4,
    })
    expect(convertRange({ kind: 'time', start: 1.5, end: null }, 'frames', source)).toEqual({
      kind: 'frames',
      start: 37,
      end: null,
    })
    expect(convertRange({ kind: 'frames', start: 37, end: null }, 'time', source)).toEqual({
      kind: 'time',
      start: 1.48,
      end: null,
    })
  })

  it('does not let float noise move a frame: 1.04 s × 25 is frame 26', () => {
    expect(convertRange({ kind: 'time', start: 0, end: 1.04 }, 'frames', source)).toEqual({
      kind: 'frames',
      start: 0,
      end: 26,
    })
  })

  it('keeps the span of real chapter times and NTSC frames, there and back', () => {
    const disc = bluray()
    const chapters: Range = { kind: 'chapters', start: 2, end: 3 }
    expect(convertRange(convertRange(chapters, 'time', disc), 'chapters', disc)).toEqual(chapters)
    const frames = convertRange(chapters, 'frames', disc)
    expect(frames).toEqual({ kind: 'frames', start: 7490, end: 30_000 })
    expect(convertRange(frames, 'chapters', disc)).toEqual(chapters)
    const later: Range = { kind: 'chapters', start: 3, end: 4 }
    expect(convertRange(later, 'frames', disc)).toEqual({
      kind: 'frames',
      start: 14_386,
      end: 43_157,
    })
    expect(convertRange(convertRange(later, 'time', disc), 'chapters', disc)).toEqual(later)
    for (const [start, end] of [
      [2, 1441],
      [7490, 30_000],
      [5, 13],
    ] as const) {
      const range: Range = { kind: 'frames', start, end }
      expect(convertRange(convertRange(range, 'time', disc), 'frames', disc)).toEqual(range)
    }
  })

  it('picks the chapters that hold the start and the end', () => {
    expect(convertRange({ kind: 'time', start: 1.2, end: 3.1 }, 'chapters', source)).toEqual(
      chapters23,
    )
    expect(convertRange({ kind: 'time', start: 1, end: 4 }, 'chapters', source)).toEqual(chapters23)
    expect(convertRange({ kind: 'frames', start: 0, end: null }, 'chapters', source)).toEqual({
      kind: 'chapters',
      start: 1,
      end: 4,
    })
    expect(convertRange({ kind: 'time', start: 4.5, end: 60 }, 'chapters', source)).toEqual({
      kind: 'chapters',
      start: 4,
      end: 4,
    })
  })

  it('keeps the whole source as the whole span', () => {
    expect(convertRange({ kind: 'full' }, 'chapters', source)).toEqual({
      kind: 'chapters',
      start: 1,
      end: 4,
    })
    expect(convertRange({ kind: 'full' }, 'time', source)).toEqual({
      kind: 'time',
      start: 0,
      end: null,
    })
    expect(convertRange(chapters23, 'full', source)).toEqual({ kind: 'full' })
  })

  it('starts from the mode’s default when the source does not give the data', () => {
    const bare = bareSource()
    expect(convertRange({ kind: 'time', start: 1, end: 2 }, 'frames', bare)).toEqual({
      kind: 'frames',
      start: 0,
      end: null,
    })
    expect(convertRange({ kind: 'frames', start: 25, end: 50 }, 'time', bare)).toEqual({
      kind: 'time',
      start: 0,
      end: null,
    })
    expect(convertRange({ kind: 'chapters', start: 7, end: 8 }, 'time', source)).toEqual({
      kind: 'time',
      start: 0,
      end: null,
    })
  })
})

describe('the text of a range', () => {
  it('names the range as the header and the Summary show it', () => {
    expect(rangeLabel({ kind: 'full' }, t)).toBe('Whole source')
    expect(rangeLabel({ kind: 'chapters', start: 2, end: 3 }, t)).toBe('Chapters 2–3')
    expect(rangeLabel({ kind: 'chapters', start: 2, end: 2 }, t)).toBe('Chapter 2')
    expect(rangeLabel({ kind: 'time', start: 90, end: 2700 }, t)).toBe('0:01:30 – 0:45:00')
    expect(rangeLabel({ kind: 'time', start: 2.5, end: null }, t)).toBe('0:00:02.500 – end')
    expect(rangeLabel({ kind: 'frames', start: 0, end: 1440 }, t)).toBe('Frames 0 – 1440')
    expect(rangeLabel({ kind: 'frames', start: 24, end: null }, t)).toBe('Frames 24 – end')
  })
})
