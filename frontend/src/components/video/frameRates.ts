export interface FrameRate {
  num: number
  den: number
}

function rate(num: number, den: number): FrameRate {
  return { num, den }
}

/** HandBrake's list; the NTSC rates are the exact fractions. */
export const FRAME_RATES: readonly FrameRate[] = [
  rate(5, 1),
  rate(10, 1),
  rate(12, 1),
  rate(15, 1),
  rate(20, 1),
  rate(24000, 1001),
  rate(24, 1),
  rate(25, 1),
  rate(30000, 1001),
  rate(30, 1),
  rate(48, 1),
  rate(50, 1),
  rate(60000, 1001),
  rate(60, 1),
  rate(72, 1),
  rate(75, 1),
  rate(90, 1),
  rate(100, 1),
  rate(120000, 1001),
  rate(120, 1),
]

/** The frame-rate list's value for "same as source" (`framerate: null`). */
export const SAME_RATE = 'source'

export function rateKey(value: { num: number; den: number }): string {
  return `${value.num}/${value.den}`
}
