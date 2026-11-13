import type { EncoderOption, JobSettings } from '@/api/types'
import type { FormatNumber } from '@/components/summary/format'
import type { ChoiceSetting, VideoEncoderDef } from '@/components/video/encoders'

type Video = NonNullable<JobSettings['video']>
type Translate = (key: string, named?: Record<string, unknown>) => string
export type OptionValue = boolean | number | string

/** The core's categories in panel order, with their i18n key under `advanced.category`. */
const CATEGORY_KEYS: Record<string, string> = {
  Basic: 'basic',
  'Rate control': 'rateControl',
  'Frame types / GOP': 'frameTypes',
  'Motion / analysis': 'motion',
  'Psycho-visual': 'psychoVisual',
  'Loop filters': 'loopFilters',
  'HDR / colour': 'hdr',
  Performance: 'performance',
}
const KNOWN = Object.keys(CATEGORY_KEYS)

function rank(id: string): number {
  return KNOWN.includes(id) ? KNOWN.indexOf(id) : KNOWN.length
}

/** The category of the custom parameters field: not a core category, always the last one. */
export const CUSTOM_CATEGORY = '(custom)'
export const HDR_CATEGORY = 'HDR / colour'

export interface Category {
  /** The core's category name, or `CUSTOM_CATEGORY`. */
  id: string
  options: EncoderOption[]
}

/** The categories that have options, in panel order, then the custom parameters. */
export function categoriesOf(options: readonly EncoderOption[]): Category[] {
  const ids = [...new Set(options.map((option) => option.category))].toSorted(
    (a, b) => rank(a) - rank(b),
  )
  return [
    ...ids.map((id) => ({ id, options: options.filter((option) => option.category === id) })),
    { id: CUSTOM_CATEGORY, options: [] },
  ]
}

/** A category the frontend does not know is shown by the core's name. */
export function categoryName(id: string, t: Translate): string {
  if (id === CUSTOM_CATEGORY) return t('advanced.category.custom')
  const key = CATEGORY_KEYS[id]
  return key === undefined ? id : t(`advanced.category.${key}`)
}

export function optionPath(key: string): string {
  return `video.advanced.${key}`
}

export function optionPointer(key: string): string {
  return `/video/advanced/${key.replaceAll('~', '~0').replaceAll('/', '~1')}`
}

/** The name the option has on the command line (`psy-rd`, `-bf`). */
export function cliName(option: EncoderOption): string {
  return option.mapping.kind === 'ffmpeg_arg' ? option.mapping.arg : option.mapping.name
}

/**
 * Decimals a float option holds as typed, whatever its step: the core takes any. A double keeps
 * this many exactly for the options' values (below 10⁵).
 */
export const FLOAT_DIGITS = 10

function choiceLabel(setting: ChoiceSetting | null | undefined, value: string): string {
  return setting?.choices.find((choice) => choice.value === value)?.label ?? value
}

/** The speed preset the job encodes with: its own, or the encoder's default. */
function presetOf(video: Video, encoder: VideoEncoderDef): string | null {
  return video.preset ?? encoder.presets?.default ?? null
}

/** The value the encoder uses while the option is not set; `undefined` when it is not known. */
export function defaultValue(
  option: EncoderOption,
  video: Video,
  encoder: VideoEncoderDef,
): OptionValue | undefined {
  const fallback = option.default
  if (fallback.kind === 'fixed') return fallback.value
  if (fallback.kind === 'encoder') return undefined
  const preset = presetOf(video, encoder)
  return preset === null ? undefined : fallback.values[preset]
}

export function valueText(
  option: EncoderOption,
  value: OptionValue,
  t: Translate,
  n: FormatNumber,
): string {
  if (typeof value === 'boolean') return value ? t('advanced.value.on') : t('advanced.value.off')
  if (option.type === 'enum') {
    return option.choices?.find((choice) => choice.value === String(value))?.label ?? String(value)
  }
  const shown =
    typeof value === 'number'
      ? n(value, { maximumFractionDigits: FLOAT_DIGITS, useGrouping: false })
      : value
  return option.unit ? t('advanced.value.unit', { value: shown, unit: option.unit }) : shown
}

/** What the encoder does while the option is not set: "4 frames (preset Slow)". */
export function defaultText(
  option: EncoderOption,
  video: Video,
  encoder: VideoEncoderDef,
  t: Translate,
  n: FormatNumber,
): string {
  const fallback = option.default
  switch (fallback.kind) {
    case 'fixed':
      return valueText(option, fallback.value, t, n)
    case 'encoder':
      return fallback.note
        ? t('advanced.default.encoderNote', { note: fallback.note })
        : t('advanced.default.encoder')
    case 'preset': {
      const preset = presetOf(video, encoder)
      if (preset === null) return t('advanced.default.byPreset')
      const named = choiceLabel(encoder.presets, preset)
      const value = fallback.values[preset]
      const text =
        value === undefined
          ? t('advanced.default.notAtPreset', { preset: named })
          : t('advanced.default.preset', { value: valueText(option, value, t, n), preset: named })
      const tune = video.tune ?? null
      if (tune === null || !(fallback.tunes ?? []).includes(tune)) return text
      return t('advanced.default.tuned', { text, tune: choiceLabel(encoder.tunes, tune) })
    }
  }
}
