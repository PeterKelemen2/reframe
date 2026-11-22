import type { MediaSource } from '@/api/types'

export interface PythonRanges {
  name: string
  source: MediaSource
  rate: number | null
  frames: number | null
  seconds: (number | null)[]
}

/** Each recorded probe with the Python core's frame rate, frame count and frame-range lengths. */
export function pythonRanges(ranges: [number, number | null][]): PythonRanges[]
