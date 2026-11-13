import type { Schemas } from '@/api/types'

/** `useI18n().t`, for the formatters that name a unit. */
export type Translate = (key: string, named?: Record<string, unknown>) => string
/** `useI18n().n`: numbers in the app's locale. */
export type FormatNumber = (value: number, options: Intl.NumberFormatOptions) => string

/** `value` with exactly `digits` decimals, in the app's locale. */
export function decimals(value: number, digits: number, n: FormatNumber): string {
  return n(value, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

type Rational = Schemas['Rational']
type ColorInfo = Schemas['ColorInfo']
type HdrInfo = Schemas['HdrInfo']
type VideoStream = Schemas['VideoStream']

const PRIMARIES: Record<string, string> = {
  bt709: 'BT.709',
  bt2020: 'BT.2020',
  smpte170m: 'BT.601 NTSC',
  bt470bg: 'BT.601 PAL',
  smpte432: 'Display P3',
}

const TRANSFERS: Record<string, string> = { smpte2084: 'PQ', 'arib-std-b67': 'HLG' }

const HDR_FORMATS: Record<Schemas['HdrFormat'], string> = {
  hdr10: 'HDR10',
  hdr10plus: 'HDR10+',
  hlg: 'HLG',
  dolby_vision: 'Dolby Vision',
}

/** `23.976`, `25`, `29.97`; `null` for an unknown rate. */
export function formatRate(rate: Rational | null | undefined, n: FormatNumber): string | null {
  if (!rate || rate.num <= 0 || rate.den <= 0) return null
  return n(rate.num / rate.den, { maximumFractionDigits: 3 })
}

/** `BT.2020 PQ`, `BT.709`; `null` when the stream does not say (the transfer of SDR is not named). */
export function colourName(color: ColorInfo | null | undefined): string | null {
  const primaries = color?.primaries ? (PRIMARIES[color.primaries] ?? color.primaries) : null
  const transfer = color?.transfer ? (TRANSFERS[color.transfer] ?? null) : null
  const parts = [primaries, transfer].filter((part) => part !== null)
  return parts.length > 0 ? parts.join(' ') : null
}

export function hdrNames(hdr: HdrInfo | null | undefined): string[] {
  return (hdr?.formats ?? []).map((format) => HDR_FORMATS[format] ?? format)
}

/** The parts of `HEVC Main 10 · 3840×2160 · 23.976 fps · HDR10 · BT.2020 PQ`. */
export function videoLine(video: VideoStream, t: Translate, n: FormatNumber): string[] {
  const parts: string[] = []
  const codec = video.display_codec || video.codec
  if (codec) parts.push(codec)
  parts.push(`${video.width}×${video.height}`)
  const rate = formatRate(video.avg_frame_rate ?? video.frame_rate, n)
  if (rate !== null) {
    parts.push(
      video.vfr ? t('summary.units.fpsVariable', { rate }) : t('summary.units.fps', { rate }),
    )
  }
  parts.push(...hdrNames(video.hdr))
  const colour = colourName(video.color)
  if (colour !== null) parts.push(colour)
  return parts
}

const KIB = 1024

/**
 * Binary units, as the file managers of Linux and Windows count them. Without `n` the number
 * is written as `toFixed` writes it.
 */
export function formatBytes(bytes: number, t: Translate, n?: FormatNumber): string {
  const fixed = (value: number, digits: number) =>
    n === undefined ? value.toFixed(digits) : decimals(value, digits, n)
  if (bytes < KIB) return t('summary.units.bytes', { value: fixed(bytes, 0) })
  if (bytes < KIB ** 2) return t('summary.units.kib', { value: fixed(bytes / KIB, 0) })
  if (bytes < KIB ** 3) return t('summary.units.mib', { value: fixed(bytes / KIB ** 2, 1) })
  return t('summary.units.gib', { value: fixed(bytes / KIB ** 3, 2) })
}

/** Bits per second as `754 kb/s` or `12.3 Mb/s`. */
export function formatBitrate(bitsPerSecond: number, t: Translate, n: FormatNumber): string {
  if (bitsPerSecond < 1_000_000) {
    return t('summary.units.kbps', { value: decimals(bitsPerSecond / 1000, 0, n) })
  }
  return t('summary.units.mbps', { value: decimals(bitsPerSecond / 1_000_000, 1, n) })
}

/** `2.40:1`. */
export function formatAspect(ratio: number, t: Translate, n: FormatNumber): string {
  return t('summary.units.aspect', { ratio: decimals(ratio, 2, n) })
}
