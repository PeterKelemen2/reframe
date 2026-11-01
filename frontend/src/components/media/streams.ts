import type { AudioStream, Schemas, SubtitleStream } from '@/api/types'

export type Disposition = Schemas['Disposition']
export type DispositionFlag = keyof Disposition
export type SourceStream = AudioStream | SubtitleStream

/** The dispositions a viewer chooses tracks by, in the order the table shows them. */
export const SHOWN_FLAGS = [
  'default',
  'original',
  'dub',
  'forced',
  'comment',
  'hearing_impaired',
  'visual_impaired',
  'captions',
  'descriptions',
  'lyrics',
  'karaoke',
  'clean_effects',
  'non_diegetic',
] as const satisfies readonly DispositionFlag[]
export type ShownFlag = (typeof SHOWN_FLAGS)[number]

/** The flags a role badge names: `shownFlags` leaves those out of the flag list. */
const FLAGS_OF_ROLE: Partial<Record<Schemas['TrackRole'], readonly DispositionFlag[]>> = {
  commentary: ['comment'],
  sdh: ['hearing_impaired', 'captions'],
  forced: ['forced'],
  description: ['visual_impaired', 'descriptions'],
}

/** Every disposition that is set, in the schema's order. */
export function setDispositions(stream: SourceStream): DispositionFlag[] {
  const disposition = stream.disposition
  if (!disposition) return []
  return (Object.keys(disposition) as DispositionFlag[]).filter((flag) => disposition[flag])
}

/** The flags shown beside the role badges; a flag that a badge already names is left out. */
export function shownFlags(stream: SourceStream): ShownFlag[] {
  const named = new Set<DispositionFlag>()
  for (const role of stream.roles ?? []) {
    if (role.evidence === 'flag') for (const flag of FLAGS_OF_ROLE[role.role] ?? []) named.add(flag)
  }
  return SHOWN_FLAGS.filter((flag) => stream.disposition?.[flag] === true && !named.has(flag))
}

const LAYOUTS: Record<string, string> = {
  mono: '1.0',
  stereo: '2.0',
  '2.1': '2.1',
  '3.0': '3.0',
  quad: '4.0',
  '4.0': '4.0',
  '4.1': '4.1',
  '5.0': '5.0',
  '5.1': '5.1',
  '6.1': '6.1',
  '7.1': '7.1',
}

/** `5.1`, `2.0`; the channel count when the layout has no common name; `null` when unknown. */
export function channelsText(stream: AudioStream): string | null {
  const layout = stream.channel_layout?.replace(/\(.*\)$/, '')
  if (layout && LAYOUTS[layout]) return LAYOUTS[layout]
  if (stream.channels > 0) return String(stream.channels)
  return stream.channel_layout ?? null
}

/** `48`, `44.1` (kHz). */
export function kiloHertz(hertz: number): string {
  return String(Number((hertz / 1000).toFixed(3)))
}

export function kbps(bitsPerSecond: number): number {
  return Math.round(bitsPerSecond / 1000)
}

/** A number of kb/s with the locale's digit grouping (`2,140`). */
export function groupedKbps(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value)
}

/** b/s as grouped kb/s. */
export function kbpsText(bitsPerSecond: number, locale: string): string {
  return groupedKbps(kbps(bitsPerSecond), locale)
}

/** The position among the source's tracks of its kind, from 1 (the table's `#`). */
export function trackNumber(stream: SourceStream): number {
  return stream.type_index + 1
}

/** BCP 47 when the file has it, else the tag ffprobe read. */
export function streamLanguage(stream: SourceStream): string | null {
  return stream.language_ietf || stream.language || null
}

/** `2 · eng · DTS-HD MA 5.1 · English Dub`: what a source choice shows. */
export function streamLabel(stream: SourceStream): string {
  const codec = stream.display_codec || stream.codec || null
  const format =
    stream.kind === 'audio' ? [codec, channelsText(stream)].filter(Boolean).join(' ') : codec
  return [String(trackNumber(stream)), streamLanguage(stream) ?? 'und', format, stream.title]
    .filter((part) => part !== null && part !== undefined && part !== '')
    .join(' · ')
}

/** `+200 ms`, `−1500 ms`, `+12 s`; `0 ms` when the track starts with the video. */
export function delayText(seconds: number): string {
  const ms = Math.round(seconds * 1000)
  if (ms === 0) return '0 ms'
  const sign = ms > 0 ? '+' : '−'
  const size = Math.abs(ms)
  return size < 10_000 ? `${sign}${size} ms` : `${sign}${Number((size / 1000).toFixed(3))} s`
}

/** `−22.5`, `2.2`: one decimal, with a real minus sign. */
export function oneDecimal(value: number): string {
  const fixed = value.toFixed(1)
  return fixed.startsWith('-') ? `−${fixed.slice(1)}` : fixed
}

/** The subtitle formats whose events carry a forced flag, which a scan counts. */
export function hasForcedEvents(stream: SubtitleStream): boolean {
  return stream.codec === 'hdmv_pgs_subtitle' || stream.codec === 'dvd_subtitle'
}

/** `1:02:03.250`, `0:04.021`. */
export function preciseDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds * 1000))
  const ms = String(total % 1000).padStart(3, '0')
  const secs = Math.floor(total / 1000)
  const hours = Math.floor(secs / 3600)
  const minutes = Math.floor((secs % 3600) / 60)
  const rest = String(secs % 60).padStart(2, '0')
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}.${ms}`
    : `${minutes}:${rest}.${ms}`
}
