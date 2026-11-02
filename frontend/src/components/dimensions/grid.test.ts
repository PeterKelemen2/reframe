import { describe, expect, it } from 'vitest'

import type { CropRect, SourceGeometry } from '@/api/types'

import { appliedCrop, gridOf, NO_CROP, snapCrop } from './grid'

function source(changes: Partial<SourceGeometry> = {}): SourceGeometry {
  return {
    width: 1920,
    height: 1080,
    rotation: 0,
    chroma_step_x: 2,
    chroma_step_y: 2,
    interlaced: false,
    chroma_assumed: false,
    ...changes,
  }
}

function rect(top = 0, bottom = 0, left = 0, right = 0): CropRect {
  return { top, bottom, left, right }
}

// The cases of the core's `test_geometry.py`: the client must apply what `compute_geometry` does.
describe('the crop the server applies', () => {
  it.each([
    ['odd values snap down to the 4:2:0 grid', source(), rect(141, 139, 3), rect(140, 138, 2)],
    [
      'interlaced 4:2:0 snaps the height to 4',
      source({ width: 720, height: 576, interlaced: true }),
      rect(6, 2),
      rect(4, 0),
    ],
    [
      '4:4:4 keeps every value',
      source({ chroma_step_x: 1, chroma_step_y: 1 }),
      rect(141, 0, 3),
      rect(141, 0, 3),
    ],
    [
      'a frame off the grid grows the far edges',
      source({ width: 853, height: 481 }),
      rect(40),
      rect(40, 1, 0, 1),
    ],
    [
      'a frame off the grid without a crop has no crop',
      source({ width: 853, height: 481 }),
      rect(),
      rect(),
    ],
    [
      '4:1:1 snaps the width to 4',
      source({ width: 720, height: 480, chroma_step_x: 4, chroma_step_y: 1 }),
      rect(0, 0, 6, 6),
      rect(0, 0, 4, 4),
    ],
    [
      'a crop that removes the full width is not applied on that axis',
      source({ width: 720, height: 480 }),
      rect(3, 0, 400, 400),
      rect(2),
    ],
    [
      'a crop of the full width is not applied, although snapped it would fit',
      source({ width: 10, height: 8 }),
      rect(3, 0, 5, 5),
      rect(2),
    ],
    [
      'a crop that leaves less than one step is not applied on that axis',
      source({ width: 9, height: 8 }),
      rect(0, 0, 4, 4),
      rect(),
    ],
    [
      'a frame less than one step high is not cropped',
      source({ width: 64, height: 1 }),
      rect(0, 0, 2),
      rect(),
    ],
    [
      'a 270° display matrix swaps the 4:2:2 steps',
      source({ rotation: 270, chroma_step_x: 2, chroma_step_y: 1 }),
      rect(3, 0, 3),
      rect(2, 0, 3),
    ],
    ['a negative value counts as 0', source(), rect(-4), rect()],
  ])('%s', (_name, src, requested, applied) => {
    expect(appliedCrop(requested, gridOf(src))).toEqual(applied)
  })

  it('measures a turned picture on its displayed sides', () => {
    expect(gridOf(source({ rotation: 90 }))).toMatchObject({ width: 1080, height: 1920 })
  })
})

describe('a manual crop', () => {
  it('says which values snapping moved and why', () => {
    expect(snapCrop(rect(141, 0, 3), NO_CROP, gridOf(source()))).toEqual({
      rect: rect(140, 0, 2),
      changes: [
        { edge: 'top', from: 141, to: 140, reason: 'grid' },
        { edge: 'left', from: 3, to: 2, reason: 'grid' },
      ],
    })
    const odd = snapCrop(rect(40), NO_CROP, gridOf(source({ width: 853, height: 481 })))
    expect(odd.changes).toEqual([
      { edge: 'bottom', from: 0, to: 1, reason: 'size' },
      { edge: 'right', from: 0, to: 1, reason: 'size' },
    ])
  })

  it('stops the moved edge one grid step before the other', () => {
    const grid = gridOf(source({ width: 320, height: 180 }))
    expect(snapCrop(rect(170, 24), rect(22, 24), grid)).toEqual({
      rect: rect(154, 24),
      changes: [{ edge: 'top', from: 170, to: 154, reason: 'inside' }],
    })
    expect(snapCrop(rect(22, 400), rect(22, 24), grid).rect).toEqual(rect(22, 156))
    expect(snapCrop(rect(0, 0, 200, 200), rect(0, 0, 200, 0), grid).rect).toEqual(
      rect(0, 0, 200, 118),
    )
  })

  it('names the grid of the source', () => {
    expect(gridOf(source({ interlaced: true }))).toMatchObject({
      subsampling: '4:2:0',
      interlaced: true,
      stepY: 4,
    })
    expect(gridOf(source({ chroma_step_x: 3, chroma_step_y: 1 })).subsampling).toBe('3×1')
  })
})
