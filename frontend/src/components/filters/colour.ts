import type { FilterSettings, Schemas } from '@/api/types'
import { colourName, hdrNames, type Translate } from '@/components/summary/format'

type VideoStream = Schemas['VideoStream']

const HDR_TRANSFERS = new Set(['smpte2084', 'arib-std-b67'])

/** PQ or HLG, by the HDR side data or the transfer. */
function isHdr(stream: VideoStream): boolean {
  return (stream.hdr?.formats ?? []).length > 0 || HDR_TRANSFERS.has(stream.color?.transfer ?? '')
}

/** `HDR10, Dolby Vision` in the list style of `locale`; `null` for none. */
export function hdrList(stream: VideoStream, locale: string): string | null {
  const names = hdrNames(stream.hdr)
  if (names.length === 0) return null
  return new Intl.ListFormat(locale, { style: 'short', type: 'unit' }).format(names)
}

/** `BT.2020 PQ (HDR10)`, `BT.709`; `null` when the stream has no colour tags. */
export function sourceColour(stream: VideoStream, t: Translate, locale: string): string | null {
  const name = colourName(stream.color)
  const hdr = hdrList(stream, locale)
  if (name === null || hdr === null) return name ?? hdr
  return t('filters.colour.withHdr', { name, hdr })
}

/** What the Colorspace and Tone mapping filters do with the source's colours. */
export type ColourOutcome =
  | { kind: 'keep' }
  | { kind: 'tonemapOnly' }
  | { kind: 'custom' }
  | { kind: 'convert'; toSdr: boolean; tonemapped: boolean }

export function colourOutcome(
  stream: VideoStream,
  filters: FilterSettings,
  presetIsCustom: boolean,
): ColourOutcome {
  const tonemapped = filters.tonemap !== undefined
  if (filters.colorspace === undefined) return { kind: tonemapped ? 'tonemapOnly' : 'keep' }
  if (presetIsCustom) return { kind: 'custom' }
  // Every Colorspace preset has an SDR transfer (BT.2020 is `bt2020-10`).
  return { kind: 'convert', toSdr: isHdr(stream), tonemapped }
}
