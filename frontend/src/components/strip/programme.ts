import type { Definitions, JobSettings, Language, MediaSource } from '@/api/types'
import { findLanguage, isUndetermined } from '@/components/base/languages'
import { audioChips, subtitleChips } from '@/components/summary/tracks'

/** Ruler steps in seconds, from a tenth of a second to six hours. */
const STEPS = [
  0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600,
] as const

/** The smallest step that puts at most `maxTicks` intervals on `duration` seconds. */
export function tickStep(duration: number, maxTicks: number): number {
  const most = Math.max(1, Math.floor(maxTicks))
  for (const step of STEPS) if (duration / step <= most) return step
  return STEPS.at(-1)!
}

export interface Tick {
  seconds: number
  /** A labelled tick; the others mark the half step between two labels. */
  major: boolean
}

/** Labelled ticks every `step` from 0 to `duration`, and a short tick between each two. */
export function ticks(duration: number, step: number): Tick[] {
  const found: Tick[] = []
  // Steps are multiples of a tenth: whole tenths keep 0.1 × 3 from landing at 0.30000000000000004.
  const tenths = Math.round(step * 10)
  for (let at = 0; at * tenths <= duration * 10 + 1e-6; at += 1) {
    const seconds = (at * tenths) / 10
    found.push({ seconds, major: true })
    const half = seconds + step / 2
    if (half < duration) found.push({ seconds: half, major: false })
  }
  return found
}

/** `m:ss` or `h:mm:ss`; tenths of a second when the step is shorter than one. */
export function clockText(seconds: number, fine = false): string {
  const tenths = Math.round(Math.max(0, seconds) * 10)
  const whole = fine ? Math.floor(tenths / 10) : Math.round(tenths / 10)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const secs = String(whole % 60).padStart(2, '0')
  const clock =
    hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`
  return fine ? `${clock}.${tenths % 10}` : clock
}

export interface Segment {
  /** Its number, counted from 1. */
  number: number
  start: number
  end: number
  title: string | null
}

/**
 * The chapters the programme shows: the source's, else the ones the job generates every N
 * minutes when the source has none; none when there is neither.
 */
export function chapterSegments(
  job: JobSettings | null,
  source: MediaSource | null,
  duration: number | null,
): Segment[] {
  const own = source?.chapters ?? []
  if (own.length > 0) {
    return own.map((chapter, at) => ({
      number: at + 1,
      start: chapter.start,
      end: chapter.end,
      title: chapter.title ?? null,
    }))
  }
  const every = job?.chapters?.generate_every
  if (job?.chapters?.enabled === false || !every || every <= 0 || duration === null) return []
  const segments: Segment[] = []
  for (let start = 0; start < duration; start += every * 60) {
    segments.push({
      number: segments.length + 1,
      start,
      end: Math.min(duration, start + every * 60),
      title: null,
    })
  }
  return segments.length > 1 ? segments : []
}

export type LaneKind = 'audio' | 'subtitle'

export interface Lane {
  /** The validation path of the output track (`audio[0]`): the lane reveals it. */
  path: string
  kind: LaneKind
  /** Its place among the output tracks of its kind, counted from 1. */
  number: number
  language: string | null
  /** The language's short code for the lane's label (`hu`, `en`); `und` when none is set. */
  code: string
  /** The language's English name; `null` when undetermined. */
  languageName: string | null
  color: string
  /** A commentary track: drawn paler. */
  commentary: boolean
  /** A subtitle burned into the picture: drawn as an outline. */
  burn: boolean
  /** A subtitle track with only its forced events. */
  forcedOnly: boolean
  /** The codec it is written in (`AAC Stereo`, `DTS-HD MA passthru`, `PGS`). */
  format: string
}

export interface LaneContext {
  definitions: Definitions | null
  languages: readonly Language[]
  colorOf: (tag: string | null | undefined) => string
  /** The text after a copied audio codec (`passthru`). */
  passthru: string
}

/** The output's flag decides; a track without metadata keeps its source's role. */
function commentary(
  metadata: { commentary?: boolean } | undefined,
  roles: readonly { role: string }[],
): boolean {
  return metadata?.commentary ?? roles.some((role) => role.role === 'commentary')
}

function codeOf(languages: readonly Language[], tag: string | null): string {
  if (isUndetermined(tag)) return 'und'
  const found = findLanguage(languages, tag)
  return found?.iso639_1 ?? found?.tag ?? tag ?? 'und'
}

/** One lane per output track: the audio tracks, then the subtitle tracks, in output order. */
export function buildLanes(
  job: JobSettings,
  source: MediaSource | null,
  context: LaneContext,
): Lane[] {
  const { definitions, languages, colorOf } = context
  const lane = (
    path: string,
    kind: LaneKind,
    index: number,
    language: string | null,
    traits: Pick<Lane, 'commentary' | 'burn' | 'forcedOnly' | 'format'>,
  ): Lane => ({
    path,
    kind,
    number: index + 1,
    language,
    code: codeOf(languages, language),
    languageName: isUndetermined(language)
      ? null
      : (findLanguage(languages, language)?.english_name ?? language),
    color: colorOf(language),
    commentary: traits.commentary,
    burn: traits.burn,
    forcedOnly: traits.forcedOnly,
    format: traits.format,
  })
  const audio = audioChips(job, source, definitions).map((chip, index) => {
    const codec = chip.stream?.display_codec || chip.stream?.codec || ''
    return lane(chip.path, 'audio', index, chip.language, {
      commentary: commentary(job.audio?.[index]?.metadata, chip.roles),
      burn: false,
      forcedOnly: false,
      format: chip.passthru
        ? [codec, context.passthru].filter(Boolean).join(' ')
        : [chip.encoder, chip.layout].filter(Boolean).join(' '),
    })
  })
  const subtitles = subtitleChips(job, source, undefined, definitions).map((chip, index) => {
    const track = job.subtitles?.[index]
    return lane(chip.path, 'subtitle', index, chip.language, {
      commentary: commentary(track?.metadata, chip.roles),
      burn: chip.action === 'burn',
      forcedOnly: track?.forced_only === true,
      format:
        chip.convertTo ?? (chip.stream?.display_codec || chip.stream?.codec || chip.external || ''),
    })
  })
  return [...audio, ...subtitles]
}

/** Where `seconds` falls on a programme of `duration` seconds, in percent, clamped to it. */
export function percentAt(seconds: number, duration: number): number {
  if (duration <= 0) return 0
  return Math.min(100, Math.max(0, (seconds / duration) * 100))
}
