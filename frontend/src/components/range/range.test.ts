import { describe, expect, it } from 'vitest'

import { createAppI18n } from '@/i18n'

import {
  canUseFrames,
  convertRange,
  formatClock,
  formatTime,
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
  ])('reads %s as %d seconds', (text, value) => {
    expect(parseTime(text)).toBe(value)
  })

  it.each(['', 'abc', '1:60', '1:2:60', '-5', '1,5', '1:', ':30', '1:30:00:00', '1e3'])(
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
