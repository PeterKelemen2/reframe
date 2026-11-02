import type { JobGeometry, Schemas } from '@/api/types'
import { formatAspect, type Translate } from '@/components/summary/format'
import { pipelineOf, type Size } from '@/components/summary/pipeline'

type Rational = Schemas['Rational']

/** Ratios people name as `16:9` rather than `1.78:1`. */
const NAMED_RATIOS = new Set([
  '1:1',
  '4:3',
  '3:2',
  '5:4',
  '16:9',
  '16:10',
  '3:4',
  '2:3',
  '4:5',
  '9:16',
])

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b)
}

function size({ width, height }: Size): string {
  return `${width}×${height}`
}

/** `16:9`, or `2.39:1` for a ratio without a name. */
export function ratioOf(width: number, height: number, sar: Rational): string {
  const across = width * sar.num
  const down = height * sar.den
  const divisor = gcd(across, down)
  const named = `${across / divisor}:${down / divisor}`
  return NAMED_RATIOS.has(named) ? named : formatAspect(across / down)
}

/**
 * `Source 1920×1080 (16:9, square) → Crop 1920×800 → Output 1920×800 · 2.40:1 · square pixels`,
 * from the same `pipelineOf` as the Summary's picture card.
 */
export function headerOf(answer: JobGeometry, t: Translate): string {
  const pipeline = pipelineOf(answer)
  if (pipeline.kind === 'no-video') return t('dimensions.header.noVideo')
  if (pipeline.kind === 'copied') {
    return t('dimensions.header.copied', { size: size(pipeline.source) })
  }
  const source = answer.source as NonNullable<JobGeometry['source']>
  const sar = source.sar ?? { num: 1, den: 1 }
  const steps = [
    t('dimensions.header.source', {
      size: size(pipeline.source),
      aspect: ratioOf(source.width, source.height, sar),
      pixels:
        sar.num === sar.den
          ? t('dimensions.header.sourceSquare')
          : t('dimensions.header.sourcePar', { par: `${sar.num}:${sar.den}` }),
    }),
  ]
  if (pipeline.crop) steps.push(t('dimensions.header.crop', { size: size(pipeline.crop) }))
  const turns = []
  if (pipeline.rotation !== 0) {
    turns.push(t('dimensions.header.rotate', { degrees: pipeline.rotation }))
  }
  if (answer.geometry?.flip_horizontal) turns.push(t('dimensions.header.flip'))
  if (turns.length > 0) steps.push(turns.join(', '))
  const geometry = answer.geometry as NonNullable<JobGeometry['geometry']>
  steps.push(
    t('dimensions.header.output', {
      size: size({ width: geometry.scaled_width, height: geometry.scaled_height }),
    }),
  )
  const pixels = pipeline.par
    ? t('dimensions.header.par', { par: `${pipeline.par.num}:${pipeline.par.den}` })
    : t('dimensions.header.square')
  return [steps.join(' → '), formatAspect(pipeline.aspect), pixels].join(' · ')
}
