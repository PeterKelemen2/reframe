import { describe, expect, it } from 'vitest'

import type { Edge } from '@/components/dimensions/grid'

import {
  fittedLength,
  LOUPE_SIZE,
  loupeView,
  STRIP_DEPTH,
  STRIP_LENGTH,
  stripRange,
  stripView,
  viewLayout,
  ZOOMS,
} from './magnifier'
import { LETTERBOX, PILLARBOX, SIZE } from './testing'

const CROP = { top: 22, bottom: 24, left: 40, right: 40 }

/** Where the crop line of `edge` is on its strip's canvas, across the strip. */
function lineOnCanvas(edge: Edge, zoom: 2 | 4 | 8): number {
  const layout = viewLayout(stripView(edge, CROP, SIZE, zoom, null, STRIP_LENGTH), CROP, SIZE)
  switch (edge) {
    case 'top':
      return layout.crop.y
    case 'bottom':
      return layout.crop.y + layout.crop.height
    case 'left':
      return layout.crop.x
    case 'right':
      return layout.crop.x + layout.crop.width
  }
}

describe('the edge strips', () => {
  it.each(ZOOMS)(
    'put each crop line on a pixel boundary in the middle of the strip at %d×',
    (zoom) => {
      for (const edge of ['top', 'bottom', 'left', 'right'] as const) {
        expect(lineOnCanvas(edge, zoom)).toBe(STRIP_DEPTH / 2)
      }
    },
  )

  it.each([
    [2, [0, 45]],
    [4, [10, 33]],
    [8, [16, 27]],
  ] as const)('show the rows around the top line at %d×', (zoom, range) => {
    const view = stripView('top', LETTERBOX, SIZE, zoom, null, STRIP_LENGTH)
    expect(stripRange('top', view, SIZE)).toEqual(range)
    expect(view.box.height * zoom).toBe(STRIP_DEPTH)
  })

  it('show the columns around the side lines', () => {
    const left = stripView('left', PILLARBOX, SIZE, 4, null, STRIP_LENGTH)
    const right = stripView('right', PILLARBOX, SIZE, 4, null, STRIP_LENGTH)
    expect(stripRange('left', left, SIZE)).toEqual([28, 51])
    expect(stripRange('right', right, SIZE)).toEqual([268, 291])
  })

  it('show along the line as many pixels as fit, around the pointer and inside the picture', () => {
    expect(stripView('top', LETTERBOX, SIZE, 4, 200, STRIP_LENGTH).box).toMatchObject({
      x: 152,
      width: 96,
    })
    expect(stripView('top', LETTERBOX, SIZE, 4, 10, STRIP_LENGTH).box.x).toBe(0)
    expect(stripView('top', LETTERBOX, SIZE, 4, 315, STRIP_LENGTH).box.x).toBe(320 - 96)
    expect(stripView('top', LETTERBOX, SIZE, 4, null, STRIP_LENGTH).box.x).toBe(160 - 48)
    expect(stripView('left', PILLARBOX, SIZE, 4, 90, STRIP_LENGTH).box).toMatchObject({
      y: 42,
      height: 96,
    })
  })

  it('show along the line the pixels of the length they are given', () => {
    expect(stripView('top', LETTERBOX, SIZE, 4, null, 256).box).toMatchObject({ x: 128, width: 64 })
    expect(stripView('top', LETTERBOX, SIZE, 8, 0, 256).box).toMatchObject({ x: 0, width: 32 })
  })

  it('are as long as the picture when it is shorter than the strip', () => {
    const view = stripView('left', PILLARBOX, SIZE, 2, 90, STRIP_LENGTH)
    expect(view.box).toMatchObject({ y: 0, height: 180 })
    expect(view.box.height * 2).toBeLessThan(STRIP_LENGTH)
  })
})

describe('viewLayout', () => {
  it('draws only the pixels that exist when the strip reaches past the picture', () => {
    const view = stripView('top', { ...LETTERBOX, top: 0 }, SIZE, 4, null, STRIP_LENGTH)
    const layout = viewLayout(view, { ...LETTERBOX, top: 0 }, SIZE)
    expect(layout.source).toEqual({ x: 112, y: 0, width: 96, height: 12 })
    expect(layout.target).toEqual({ x: 0, y: 48, width: 384, height: 48 })
    expect(layout).toMatchObject({ width: 384, height: 96 })
  })

  it('puts the picture and the kept rectangle on the canvas at the zoom', () => {
    const view = stripView('bottom', LETTERBOX, SIZE, 8, null, STRIP_LENGTH)
    const layout = viewLayout(view, LETTERBOX, SIZE)
    expect(view.box.y).toBe(150)
    expect(layout.picture).toMatchObject({ y: -150 * 8, height: 180 * 8 })
    expect(layout.crop).toMatchObject({ y: (22 - 150) * 8, height: 134 * 8 })
  })

  it('has nothing to draw for a view off the picture', () => {
    const layout = viewLayout({ box: { x: -50, y: 0, width: 40, height: 40 }, zoom: 4 }, CROP, SIZE)
    expect(layout.source).toBeNull()
  })
})

describe('fittedLength', () => {
  it('is the longest length within the room that shows whole pixels at every zoom', () => {
    expect(fittedLength(262)).toBe(256)
    expect(fittedLength(256)).toBe(256)
    expect(fittedLength(255.5)).toBe(248)
    for (const zoom of ZOOMS) expect(fittedLength(517) % zoom).toBe(0)
  })

  it('is 0 when there is no room', () => {
    expect(fittedLength(-2)).toBe(0)
  })
})

describe('loupeView', () => {
  it('draws the pixel under the pointer in the middle of the loupe', () => {
    const point = { x: 100.7, y: 30.2 }
    const view = loupeView(point)
    // The canvas position of the middle of source pixel (100, 30).
    expect((Math.floor(point.x) + 0.5 - view.box.x) * view.zoom).toBe(LOUPE_SIZE / 2)
    expect((Math.floor(point.y) + 0.5 - view.box.y) * view.zoom).toBe(LOUPE_SIZE / 2)
    expect(view.box.width * view.zoom).toBe(LOUPE_SIZE)
  })
})
