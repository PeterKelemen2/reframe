import type { JobSettings, MediaSource, Schemas } from '@/api/types'
import type { Translate } from '@/components/summary/format'

/** The part of the source a job encodes. */
export type Range = NonNullable<JobSettings['range']>
export type RangeKind = Range['kind']

type VideoStream = Schemas['VideoStream']

export const FULL: Range = { kind: 'full' }

/** Chapter times come in whole microseconds, so a frame edge in seconds can be off by half of one. */
const SECONDS_TOLERANCE = 1e-6
/** The same in frames (up to 240 fps), and float noise: `1.04 × 25` is 26.000000000000004. */
const FRAMES_TOLERANCE = 1e-3

const SECONDS = /^(\d+(?:\.\d*)?|\.\d+)$/
const MINUTES = /^(\d+):([0-5]?\d(?:\.\d*)?)$/
const HOURS = /^(\d+):([0-5]?\d):([0-5]?\d(?:\.\d*)?)$/

function milliseconds(seconds: number): number {
  return Math.round(seconds * 1000) / 1000
}

/**
 * Seconds from `H:MM:SS.mmm`, `MM:SS` or plain seconds, to the millisecond that the field shows;
 * `null` when the text is none of them.
 */
export function parseTime(text: string): number | null {
  const value = text.trim()
  let match = SECONDS.exec(value)
  if (match) return milliseconds(Number(match[1]))
  match = MINUTES.exec(value)
  if (match) return milliseconds(Number(match[1]) * 60 + Number(match[2]))
  match = HOURS.exec(value)
  if (match) return milliseconds(Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]))
  return null
}

function clockParts(seconds: number): { clock: string; fraction: number } {
  const total = Math.round(Math.max(0, seconds) * 1000)
  const fraction = total % 1000
  const whole = (total - fraction) / 1000
  const hours = Math.floor(whole / 3600)
  const minutes = String(Math.floor((whole % 3600) / 60)).padStart(2, '0')
  const secs = String(whole % 60).padStart(2, '0')
  return { clock: `${hours}:${minutes}:${secs}`, fraction }
}

/** `0:01:30.000`. */
export function formatTime(seconds: number): string {
  const { clock, fraction } = clockParts(seconds)
  return `${clock}.${String(fraction).padStart(3, '0')}`
}

/** `0:01:30`, with the milliseconds only when there are some (`0:00:02.500`). */
export function formatClock(seconds: number): string {
  const { clock, fraction } = clockParts(seconds)
  return fraction === 0 ? clock : `${clock}.${String(fraction).padStart(3, '0')}`
}

/** A non-negative whole number (a frame); `null` for anything else. */
export function parseFrame(text: string): number | null {
  const value = text.trim()
  return /^\d+$/.test(value) ? Number(value) : null
}

function videoOf(source: MediaSource | null): VideoStream | null {
  return source?.video?.[0] ?? null
}

/** The source's duration: the container's, else the main video stream's. */
export function sourceDuration(source: MediaSource | null): number | null {
  return source?.container?.duration ?? videoOf(source)?.duration ?? null
}

/** Rates that a counted rate snaps to, within 0.2 %, as the command builder snaps them. */
const STANDARD_RATES: readonly (readonly [bigint, bigint])[] = [
  [24000n, 1001n],
  [24n, 1n],
  [25n, 1n],
  [30000n, 1001n],
  [30n, 1n],
  [48n, 1n],
  [50n, 1n],
  [60000n, 1001n],
  [60n, 1n],
  [100n, 1n],
  [120000n, 1001n],
  [120n, 1n],
]

function abs(value: bigint): bigint {
  return value < 0n ? -value : value
}

function gcd(a: bigint, b: bigint): bigint {
  return b === 0n ? a : gcd(b, a % b)
}

/** The exact value of a non-negative float as `[numerator, denominator]`. */
function exactly(value: number): [bigint, bigint] {
  let scaled = value
  let den = 1n
  while (!Number.isInteger(scaled)) {
    scaled *= 2
    den *= 2n
  }
  return [BigInt(scaled), den]
}

/** Python's `Fraction.limit_denominator`: the closest fraction with a denominator up to `max`. */
function limitDenominator(num: bigint, den: bigint, max: bigint): number {
  if (den <= max) return Number(num) / Number(den)
  let [p0, q0, p1, q1] = [0n, 1n, 1n, 0n]
  let [n, d] = [num, den]
  for (;;) {
    const a = n / d
    const q2 = q0 + a * q1
    if (q2 > max) break
    ;[p0, q0, p1, q1] = [p1, q1, p0 + a * p1, q2]
    ;[n, d] = [d, n - a * d]
  }
  const k = (max - q0) / q1
  return 2n * d * (q0 + k * q1) <= den
    ? Number(p1) / Number(q1)
    : Number(p0 + k * p1) / Number(q0 + k * q1)
}

/** `frames ÷ seconds` snapped to a standard rate, with the builder's exact arithmetic. */
function countedRate(frames: number, seconds: number): number {
  const [secondsNum, secondsDen] = exactly(seconds)
  const num = BigInt(frames) * secondsDen
  const den = secondsNum
  let closest: readonly [bigint, bigint] = STANDARD_RATES[0]!
  let closestOff: readonly [bigint, bigint] | null = null
  for (const standard of STANDARD_RATES) {
    const [sn, sd] = standard
    const off = [abs(num * sd - sn * den), den * sd] as const
    if (closestOff === null || off[0] * closestOff[1] < closestOff[0] * off[1]) {
      closest = standard
      closestOff = off
    }
  }
  const [sn, sd] = closest
  if (abs(num * sd - sn * den) * 500n <= sn * den) return Number(sn) / Number(sd)
  const divisor = gcd(num, den)
  return limitDenominator(num / divisor, den / divisor, 1001n)
}

/**
 * The frame rate the command builder turns frames into time with, in frames per second: the
 * average one, else the frame count ÷ the stream's duration snapped to a standard rate, else
 * the stream's rate.
 */
export function frameRate(source: MediaSource | null): number | null {
  const video = videoOf(source)
  if (video === null) return null
  const average = video.avg_frame_rate
  if (average != null && average.num > 0) return average.num / average.den
  if (video.frame_count && video.duration) return countedRate(video.frame_count, video.duration)
  const rate = video.frame_rate
  return rate != null && rate.num > 0 ? rate.num / rate.den : null
}

/** Python's `round()`: a half goes to the even neighbour. */
function roundHalfEven(value: number): number {
  const floor = Math.floor(value)
  const fraction = value - floor
  if (fraction !== 0.5) return Math.round(value)
  return floor % 2 === 0 ? floor : floor + 1
}

/** Frames of the main video stream: its count, else duration × frame rate. */
export function frameCount(source: MediaSource | null): number | null {
  const video = videoOf(source)
  if (video === null) return null
  if (video.frame_count != null) return video.frame_count
  const fps = frameRate(source)
  const duration = sourceDuration(source)
  return fps === null || duration === null ? null : roundHalfEven(duration * fps)
}

/** The source can take a range in frames: the command builder finds a frame rate. */
export function canUseFrames(source: MediaSource | null): boolean {
  return frameRate(source) !== null
}

export function hasChapters(source: MediaSource | null): boolean {
  return (source?.chapters?.length ?? 0) > 0
}

/**
 * Seconds of the source that the job's range covers, clamped to the source as the server's
 * `range_duration` clamps them; `null` when the source does not say.
 */
export function rangeSeconds(job: { range?: Range }, source: MediaSource | null): number | null {
  const range = job.range ?? FULL
  const duration = sourceDuration(source)
  switch (range.kind) {
    case 'full':
      return duration
    case 'time': {
      const end = range.end ?? null
      if (duration === null) return end === null ? null : Math.max(0, end - range.start)
      return Math.max(0, (end === null ? duration : Math.min(end, duration)) - range.start)
    }
    case 'chapters': {
      const chapters = source?.chapters ?? []
      const first = chapters[range.start - 1]
      const last = chapters[Math.min(range.end, chapters.length) - 1]
      return first && last ? Math.max(0, last.end - first.start) : null
    }
    case 'frames': {
      const fps = frameRate(source)
      if (fps === null) return null
      const total = frameCount(source)
      let last = range.end ?? total
      if (last === null) return null
      if (total !== null) last = Math.min(last, total)
      return Math.max(0, last - range.start) / fps
    }
  }
}

/** The span of `range` in seconds (`end: null` = to the end); `null` without the data. */
export function rangeSpan(
  range: Range,
  source: MediaSource | null,
): { start: number; end: number | null } | null {
  switch (range.kind) {
    case 'full':
      return { start: 0, end: null }
    case 'time':
      return { start: range.start, end: range.end ?? null }
    case 'chapters': {
      const chapters = source?.chapters ?? []
      const first = chapters[range.start - 1]
      const last = chapters[Math.min(range.end, chapters.length) - 1]
      return first && last ? { start: first.start, end: last.end } : null
    }
    case 'frames': {
      const fps = frameRate(source)
      if (fps === null) return null
      return { start: range.start / fps, end: range.end == null ? null : range.end / fps }
    }
  }
}

function defaultOf(kind: RangeKind, source: MediaSource | null): Range {
  switch (kind) {
    case 'full':
      return FULL
    case 'time':
      return { kind: 'time', start: 0, end: null }
    case 'frames':
      return { kind: 'frames', start: 0, end: null }
    case 'chapters':
      return { kind: 'chapters', start: 1, end: Math.max(1, source?.chapters?.length ?? 1) }
  }
}

/** The 1-based chapters that hold `start` and `end` (the last chapter for an open end). */
function chaptersHolding(
  start: number,
  end: number | null,
  source: MediaSource | null,
): Range | null {
  const chapters = source?.chapters ?? []
  if (chapters.length === 0) return null
  let first = chapters.findLastIndex((chapter) => chapter.start <= start + SECONDS_TOLERANCE)
  if (first < 0) first = 0
  let last =
    end === null ? -1 : chapters.findIndex((chapter) => chapter.end >= end - SECONDS_TOLERANCE)
  if (last < 0) last = chapters.length - 1
  return { kind: 'chapters', start: first + 1, end: Math.max(first, last) + 1 }
}

/**
 * `range` in another mode, keeping its span where the source gives the data: seconds from
 * chapters or frames (not rounded: the span stays exact), frames from seconds with the
 * builder's frame rate (the start rounded down, the end up), and the chapters that hold the
 * start and the end. Else the mode's default.
 */
export function convertRange(range: Range, kind: RangeKind, source: MediaSource | null): Range {
  if (range.kind === kind) return range
  if (kind === 'full') return FULL
  const span = rangeSpan(range, source)
  if (span === null) return defaultOf(kind, source)
  switch (kind) {
    case 'time':
      return { kind: 'time', start: span.start, end: span.end }
    case 'frames': {
      const fps = frameRate(source)
      if (fps === null) return defaultOf(kind, source)
      return {
        kind: 'frames',
        start: Math.max(0, Math.floor(span.start * fps + FRAMES_TOLERANCE)),
        end: span.end === null ? null : Math.ceil(span.end * fps - FRAMES_TOLERANCE),
      }
    }
    case 'chapters':
      return chaptersHolding(span.start, span.end, source) ?? defaultOf(kind, source)
  }
}

/** `useI18n().n`: a number in the app's locale. */
export type FormatNumber = (value: number) => string

/** "Whole source", "Chapters 2–3", "0:01:30 – 0:45:00", "Frames 0 – 1,440". */
export function rangeLabel(range: Range, t: Translate, n: FormatNumber): string {
  switch (range.kind) {
    case 'full':
      return t('range.label.full')
    case 'chapters':
      return range.start === range.end
        ? t('range.label.chapter', { number: n(range.start) })
        : t('range.label.chapters', { start: n(range.start), end: n(range.end) })
    case 'time':
      return range.end == null
        ? t('range.label.timeToEnd', { start: formatClock(range.start) })
        : t('range.label.time', { start: formatClock(range.start), end: formatClock(range.end) })
    case 'frames':
      return range.end == null
        ? t('range.label.framesToEnd', { start: n(range.start) })
        : t('range.label.frames', { start: n(range.start), end: n(range.end) })
  }
}
