export interface FrameRate {
  num: number
  den: number
  label: string
}

function rate(num: number, den: number, label: string): FrameRate {
  return { num, den, label }
}

/** HandBrake's list; the NTSC rates are the exact fractions. */
export const FRAME_RATES: readonly FrameRate[] = [
  rate(5, 1, '5'),
  rate(10, 1, '10'),
  rate(12, 1, '12'),
  rate(15, 1, '15'),
  rate(20, 1, '20'),
  rate(24000, 1001, '23.976'),
  rate(24, 1, '24'),
  rate(25, 1, '25'),
  rate(30000, 1001, '29.97'),
  rate(30, 1, '30'),
  rate(48, 1, '48'),
  rate(50, 1, '50'),
  rate(60000, 1001, '59.94'),
  rate(60, 1, '60'),
  rate(72, 1, '72'),
  rate(75, 1, '75'),
  rate(90, 1, '90'),
  rate(100, 1, '100'),
  rate(120000, 1001, '119.88'),
  rate(120, 1, '120'),
]

/** The frame-rate list's value for "same as source" (`framerate: null`). */
export const SAME_RATE = 'source'

export function rateKey(value: { num: number; den: number }): string {
  return `${value.num}/${value.den}`
}
