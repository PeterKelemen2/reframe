import type { Schemas } from '@/api/types'

type JobGeometry = Schemas['JobGeometry']
type Rational = Schemas['Rational']

export interface Size {
  width: number
  height: number
}

/** The picture from the source to the output, as `jobs/geometry` computes it. */
export type Pipeline =
  | { kind: 'no-video' }
  | { kind: 'copied'; source: Size }
  | {
      kind: 'encoded'
      source: Size
      /** `null` when nothing is cropped. */
      crop: Size | null
      /** Clockwise degrees; 0 for none. */
      rotation: number
      /** `null` when the cropped size is kept. */
      scale: Size | null
      aspect: number
      /** The output's pixel aspect; `null` for square pixels. */
      par: Rational | null
      upscaled: boolean
      notes: string[]
    }

export function pipelineOf(answer: JobGeometry): Pipeline {
  const { source, geometry } = answer
  if (source === null) return { kind: 'no-video' }
  const from = { width: source.width, height: source.height }
  if (geometry === null) return { kind: 'copied', source: from }
  const { crop } = geometry
  const cropped = crop.top + crop.bottom + crop.left + crop.right > 0
  const scaled =
    geometry.scaled_width !== geometry.cropped_width ||
    geometry.scaled_height !== geometry.cropped_height
  const sar = geometry.output_sar
  return {
    kind: 'encoded',
    source: from,
    crop: cropped ? { width: geometry.cropped_width, height: geometry.cropped_height } : null,
    rotation: geometry.rotation,
    scale: scaled ? { width: geometry.scaled_width, height: geometry.scaled_height } : null,
    aspect: geometry.display_aspect,
    par: sar.num === sar.den ? null : sar,
    upscaled: geometry.upscaled,
    notes: geometry.notes ?? [],
  }
}
