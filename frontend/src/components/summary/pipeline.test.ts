import { describe, expect, it } from 'vitest'

import type { Schemas } from '@/api/types'

import { pipelineOf } from './pipeline'

type JobGeometry = Schemas['JobGeometry']

const SOURCE = {
  width: 320,
  height: 180,
  sar: { num: 1, den: 1 },
  rotation: 0,
  chroma_step_x: 2,
  chroma_step_y: 2,
  interlaced: false,
  chroma_assumed: false,
} as const

/** As the real server answered for letterbox.mkv with a manual crop of 22 / 24 lines. */
function cropped(overrides: Partial<NonNullable<JobGeometry['geometry']>> = {}): JobGeometry {
  return {
    source: SOURCE,
    geometry: {
      crop: { top: 22, bottom: 24, left: 0, right: 0 },
      cropped_width: 320,
      cropped_height: 134,
      scaled_width: 320,
      scaled_height: 134,
      output_sar: { num: 1, den: 1 },
      display_aspect: 2.388059701492537,
      rotation: 0,
      upscaled: false,
      notes: [],
      filter_rotation: 0,
      flip_horizontal: false,
      ...overrides,
    },
  }
}

describe('the picture pipeline', () => {
  it('has a crop step only when something is cropped and a scale step only when the size changes', () => {
    expect(pipelineOf(cropped())).toMatchObject({
      kind: 'encoded',
      source: { width: 320, height: 180 },
      crop: { width: 320, height: 134 },
      scale: null,
      par: null,
    })
    const plain = pipelineOf(
      cropped({ crop: { top: 0, bottom: 0, left: 0, right: 0 }, cropped_height: 180 }),
    )
    expect(plain).toMatchObject({ crop: null, scale: { width: 320, height: 134 } })
  })

  it('names a pixel aspect that is not square', () => {
    const anamorphic = pipelineOf(cropped({ scaled_width: 240, output_sar: { num: 4, den: 3 } }))
    expect(anamorphic).toMatchObject({
      scale: { width: 240, height: 134 },
      par: { num: 4, den: 3 },
    })
  })

  it('shows a copied video and a source without video', () => {
    expect(pipelineOf({ source: SOURCE, geometry: null })).toEqual({
      kind: 'copied',
      source: { width: 320, height: 180 },
    })
    expect(pipelineOf({ source: null, geometry: null })).toEqual({ kind: 'no-video' })
  })
})
