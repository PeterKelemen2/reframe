import { describe, expect, it } from 'vitest'

import { fileName, formatDuration } from './format'

describe('formatDuration', () => {
  it.each([
    [3725.4, '1:02:05'],
    [65, '1:05'],
    [59.6, '1:00'],
    [0, '0:00'],
    [null, null],
    [undefined, null],
    [Number.NaN, null],
    [-1, null],
  ])('%s s → %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected)
  })
})

describe('fileName', () => {
  it.each([
    ['/media/Show/E01.mkv', 'E01.mkv'],
    ['D:\\Media\\Movie.mkv', 'Movie.mkv'],
    ['/media/Show/', 'Show'],
  ])('%s → %s', (path, expected) => {
    expect(fileName(path)).toBe(expected)
  })
})
