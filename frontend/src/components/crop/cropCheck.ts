import type { CropRect } from '@/api/types'
import type { PictureSize } from '@/stores/crop'

/** A rectangle of the source picture, in pixels. */
export interface Box {
  x: number
  y: number
  width: number
  height: number
}

/** What the page asks the crop check worker: the PNG of one frame and the bands to measure. */
export interface CheckRequest {
  key: string
  blob: Blob
  bands: Box[]
}

export interface CheckResult {
  key: string
  /** The luma variance of each band, in the order asked. */
  variances: number[]
  lost: boolean
}

/** The worker could not read the frame. */
export interface CheckFailure {
  key: string
  error: string
}

export type CheckAnswer = CheckResult | CheckFailure

/**
 * Above this luma variance (0–255 scale) a removed band holds picture. The black bars of the
 * `letterbox` fixture's frames measure at most 6.1 (the bicubic chroma rings into them); its
 * narrowest band of picture, 443; two rows of picture in a 24-row band, 1 718.
 */
export const LOSES_CONTENT_VARIANCE = 64

/** The parts of the picture the crop removes, without overlaps; none for an edge of 0. */
export function removedBands(rect: CropRect, size: PictureSize): Box[] {
  const { width, height } = size
  const middle = height - rect.top - rect.bottom
  const bands: Box[] = [
    { x: 0, y: 0, width, height: rect.top },
    { x: 0, y: height - rect.bottom, width, height: rect.bottom },
    { x: 0, y: rect.top, width: rect.left, height: middle },
    { x: width - rect.right, y: rect.top, width: rect.right, height: middle },
  ]
  return bands.filter((band) => band.width > 0 && band.height > 0)
}

/** The variance of the BT.709 luma of RGBA pixels (canvas `ImageData`), on a 0–255 scale. */
export function lumaVariance(rgba: Uint8ClampedArray): number {
  const count = rgba.length / 4
  let sum = 0
  let squares = 0
  for (let i = 0; i < rgba.length; i += 4) {
    const luma = 0.2126 * rgba[i]! + 0.7152 * rgba[i + 1]! + 0.0722 * rgba[i + 2]!
    sum += luma
    squares += luma * luma
  }
  const mean = sum / count
  return squares / count - mean * mean
}

export function losesContent(variances: readonly number[]): boolean {
  return variances.some((variance) => variance > LOSES_CONTENT_VARIANCE)
}
