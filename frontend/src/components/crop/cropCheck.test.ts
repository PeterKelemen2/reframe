import { describe, expect, it } from 'vitest'

import { LOSES_CONTENT_VARIANCE, losesContent, lumaVariance, removedBands } from './cropCheck'
import { LETTERBOX, SIZE } from './testing'

function pixels(...rgb: [number, number, number][]): Uint8ClampedArray {
  return new Uint8ClampedArray(rgb.flatMap(([r, g, b]) => [r, g, b, 255]))
}

describe('removedBands', () => {
  it('gives the rows of a letterbox crop and nothing for the edges of 0', () => {
    expect(removedBands(LETTERBOX, SIZE)).toEqual([
      { x: 0, y: 0, width: 320, height: 22 },
      { x: 0, y: 156, width: 320, height: 24 },
    ])
  })

  it('gives the side columns between the top and bottom bands, so no pixel counts twice', () => {
    const bands = removedBands({ top: 22, bottom: 24, left: 40, right: 40 }, SIZE)
    expect(bands.slice(2)).toEqual([
      { x: 0, y: 22, width: 40, height: 134 },
      { x: 280, y: 22, width: 40, height: 134 },
    ])
    const area = bands.reduce((sum, band) => sum + band.width * band.height, 0)
    expect(area).toBe(320 * 180 - 240 * 134)
  })
})

describe('lumaVariance', () => {
  it('is 0 for a flat band of any colour', () => {
    expect(lumaVariance(pixels([0, 0, 0], [0, 0, 0]))).toBe(0)
    expect(lumaVariance(pixels([200, 30, 90], [200, 30, 90], [200, 30, 90]))).toBeCloseTo(0, 9)
  })

  it('weighs the channels as BT.709 luma and ignores alpha', () => {
    // Black and red, half each: the variance is (luma of red / 2)².
    const red = pixels([0, 0, 0], [255, 0, 0])
    red[3] = 0
    expect(lumaVariance(red)).toBeCloseTo(((0.2126 * 255) / 2) ** 2, 6)
    expect(lumaVariance(pixels([0, 0, 0], [0, 255, 0]))).toBeCloseTo(((0.7152 * 255) / 2) ** 2, 6)
  })
})

describe('losesContent', () => {
  it('passes the noise of black bars and flags a band with picture in it', () => {
    // The highest band variance of the letterbox fixture's bars, and two picture rows in a bar.
    expect(losesContent([0.46, 0.39])).toBe(false)
    expect(losesContent([0.39, 1720])).toBe(true)
    expect(losesContent([LOSES_CONTENT_VARIANCE])).toBe(false)
  })

  it('passes a crop that removes nothing', () => {
    expect(losesContent([])).toBe(false)
  })
})
