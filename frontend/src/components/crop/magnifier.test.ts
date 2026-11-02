import { describe, expect, it } from 'vitest'

import {
  type Edge,
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
  const layout = viewLayout(stripView(edge, CROP, SIZE, zoom, null), CROP, SIZE)
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
    const view = stripView('top', LETTERBOX, SIZE, zoom, null)
    expect(stripRange('top', view, SIZE)).toEqual(range)
    expect(view.box.height * zoom).toBe(STRIP_DEPTH)
  })

  it('show the columns around the side lines', () => {
    const left = stripView('left', PILLARBOX, SIZE, 4, null)
    const right = stripView('right', PILLARBOX, SIZE, 4, null)
    expect(stripRange('left', left, SIZE)).toEqual([28, 51])
    expect(stripRange('right', right, SIZE)).toEqual([268, 291])
  })

  it('show along the line as many pixels as fit, around the pointer and inside the picture', () => {
    expect(stripView('top', LETTERBOX, SIZE, 4, 200).box).toMatchObject({ x: 152, width: 96 })
    expect(stripView('top', LETTERBOX, SIZE, 4, 10).box.x).toBe(0)
    expect(stripView('top', LETTERBOX, SIZE, 4, 315).box.x).toBe(320 - 96)
    expect(stripView('top', LETTERBOX, SIZE, 4, null).box.x).toBe(160 - 48)
    expect(stripView('left', PILLARBOX, SIZE, 4, 90).box).toMatchObject({ y: 42, height: 96 })
  })

  it('are as long as the picture when it is shorter than the strip', () => {
    const view = stripView('left', PILLARBOX, SIZE, 2, 90)
    expect(view.box).toMatchObject({ y: 0, height: 180 })
    expect(view.box.height * 2).toBeLessThan(STRIP_LENGTH)
  })
})

describe('viewLayout', () => {
  it('draws only the pixels that exist when the strip reaches past the picture', () => {
    const view = stripView('top', { ...LETTERBOX, top: 0 }, SIZE, 4, null)
    const layout = viewLayout(view, { ...LETTERBOX, top: 0 }, SIZE)
    expect(layout.source).toEqual({ x: 112, y: 0, width: 96, height: 12 })
    expect(layout.target).toEqual({ x: 0, y: 48, width: 384, height: 48 })
    expect(layout).toMatchObject({ width: 384, height: 96 })
  })

  it('puts the picture and the kept rectangle on the canvas at the zoom', () => {
    const view = stripView('bottom', LETTERBOX, SIZE, 8, null)
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

describe('loupeView', () => {
  it('centres the loupe on the pixel under the pointer', () => {
    expect(loupeView({ x: 100.7, y: 30.2 })).toEqual({
      box: { x: 80, y: 10, width: 40, height: 40 },
      zoom: 4,
    })
  })
})
