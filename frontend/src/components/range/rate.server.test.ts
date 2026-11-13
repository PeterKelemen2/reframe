import { describe, expect, it } from 'vitest'

import { frameCount, frameRate, rangeSeconds } from './range'
import { pythonRanges } from './pythonRanges.mjs'

const RANGES: [number, number | null][] = [
  [10, 50],
  [0, null],
  [5, 1_000_000],
]
const probes = pythonRanges(RANGES)

describe('the frame arithmetic against the Python core', () => {
  it('covers the recorded probes, the one without an average frame rate too', () => {
    const vfr = probes.find((probe) => probe.name === 'vfr.json')
    expect(vfr?.source.video?.[0]?.avg_frame_rate).toBeNull()
    expect(vfr?.rate).toBe(6000 / 157)
    expect(probes.length).toBeGreaterThan(20)
  })

  it.each(probes.map((probe) => [probe.name, probe] as const))(
    '%s: the same frame rate, frame count and range lengths',
    (_name, probe) => {
      expect(frameRate(probe.source)).toBe(probe.rate)
      expect(frameCount(probe.source)).toBe(probe.frames)
      expect(
        RANGES.map(([start, end]) =>
          rangeSeconds({ range: { kind: 'frames', start, end } }, probe.source),
        ),
      ).toEqual(probe.seconds)
    },
  )
})
