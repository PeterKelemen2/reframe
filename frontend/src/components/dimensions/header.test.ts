import { describe, expect, it } from 'vitest'

import { formatters } from '@/components/summary/testing'

import { headerOf, ratioOf } from './header'
import { geometryOf, LETTERBOX } from './testing'

const { t, n } = formatters()

describe('the pipeline header', () => {
  it("reads like the plan's example, with the crop and the output", () => {
    const hd = { ...LETTERBOX, width: 1920, height: 1080 }
    const answer = geometryOf(hd, {
      crop: { top: 140, bottom: 140, left: 0, right: 0 },
      cropped_width: 1920,
      cropped_height: 800,
      scaled_width: 1920,
      scaled_height: 800,
      display_aspect: 2.4,
    })
    expect(headerOf(answer, t, n)).toBe(
      'Source 1920×1080 (16:9, square) → Crop 1920×800 → Output 1920×800 · 2.40:1 · square pixels',
    )
  })

  it('names the rotation, the flip and an anamorphic pixel aspect', () => {
    const dvd = { ...LETTERBOX, width: 720, height: 480, sar: { num: 32, den: 27 } }
    const answer = geometryOf(dvd, {
      scaled_width: 480,
      scaled_height: 720,
      output_sar: { num: 27, den: 32 },
      display_aspect: 9 / 16,
      rotation: 90,
      filter_rotation: 90,
      flip_horizontal: true,
    })
    expect(headerOf(answer, t, n)).toBe(
      'Source 720×480 (16:9, pixel aspect 32:27) → Rotate 90°, flip → Output 480×720 · 0.56:1 · pixel aspect 27:32',
    )
  })

  it('says when the video is copied or missing', () => {
    expect(headerOf({ source: LETTERBOX, geometry: null }, t, n)).toBe(
      'Source 320×180: the video is copied, so the picture is not changed',
    )
    expect(headerOf({ source: null, geometry: null }, t, n)).toBe('The source has no video.')
  })

  it('names common ratios and gives the others as a number', () => {
    expect(ratioOf(1440, 1080, { num: 1, den: 1 }, t, n)).toBe('4:3')
    expect(ratioOf(1920, 804, { num: 1, den: 1 }, t, n)).toBe('2.39:1')
  })

  it('names a rotation or a flip alone', () => {
    const turned = geometryOf(LETTERBOX, { rotation: 180, filter_rotation: 180 })
    expect(headerOf(turned, t, n)).toContain('→ Rotate 180° →')
    const flipped = geometryOf(LETTERBOX, { flip_horizontal: true })
    expect(headerOf(flipped, t, n)).toContain('→ Flip →')
  })

  it('writes a ratio without a name in the app locale', () => {
    const german = formatters('de')
    expect(ratioOf(1920, 804, { num: 1, den: 1 }, german.t, german.n)).toBe('2,39:1')
  })
})
