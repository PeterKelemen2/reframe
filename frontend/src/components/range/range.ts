import type { JobSettings, MediaSource, Schemas } from '@/api/types'
import type { Translate } from '@/components/summary/format'

/** The part of the source a job encodes. */
export type Range = NonNullable<JobSettings['range']>
export type RangeKind = Range['kind']

type Rational = Schemas['Rational']
type VideoStream = Schemas['VideoStream']

export const FULL: Range = { kind: 'full' }

/** Float noise (`4.000000001 × 25`) must not round a frame number past its true value. */
const EPSILON = 1e-6

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

function usable(rate: Rational | null | undefined): rate is Rational {
  return rate != null && rate.num > 0 && rate.den > 0
}

/** The average frame rate (else the stream's frame rate) in frames per second. */
export function frameRate(source: MediaSource | null): number | null {
  const video = videoOf(source)
  const rate = video?.avg_frame_rate ?? video?.frame_rate
  return usable(rate) ? rate.num / rate.den : null
}

/** Frames of the main video stream: its count, else duration × frame rate. */
export function frameCount(source: MediaSource | null): number | null {
  const video = videoOf(source)
  if (video === null) return null
  if (video.frame_count != null) return video.frame_count
  const fps = frameRate(source)
  const duration = sourceDuration(source)
  return fps === null || duration === null ? null : Math.round(duration * fps)
}

/**
 * The source can take a range in frames: the command builder needs a main video stream with a
 * frame rate, or with a frame count and a duration.
 */
export function canUseFrames(source: MediaSource | null): boolean {
  const video = videoOf(source)
  if (video === null) return false
  return (
    usable(video.avg_frame_rate) ||
    usable(video.frame_rate) ||
    Boolean(video.frame_count && video.duration)
  )
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
function spanOf(
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
  let first = chapters.findLastIndex((chapter) => chapter.start <= start + EPSILON)
  if (first < 0) first = 0
  let last = end === null ? -1 : chapters.findIndex((chapter) => chapter.end >= end - EPSILON)
  if (last < 0) last = chapters.length - 1
  return { kind: 'chapters', start: first + 1, end: Math.max(first, last) + 1 }
}

/**
 * `range` in another mode, keeping its span where the source gives the data: seconds from
 * chapters or frames, frames from seconds with the average frame rate (the start rounded
 * down, the end up), and the chapters that hold the start and the end. Else the mode's default.
 */
export function convertRange(range: Range, kind: RangeKind, source: MediaSource | null): Range {
  if (range.kind === kind) return range
  if (kind === 'full') return FULL
  const span = spanOf(range, source)
  if (span === null) return defaultOf(kind, source)
  switch (kind) {
    case 'time':
      return {
        kind: 'time',
        start: milliseconds(span.start),
        end: span.end === null ? null : milliseconds(span.end),
      }
    case 'frames': {
      const fps = frameRate(source)
      if (fps === null) return defaultOf(kind, source)
      return {
        kind: 'frames',
        start: Math.max(0, Math.floor(span.start * fps + EPSILON)),
        end: span.end === null ? null : Math.ceil(span.end * fps - EPSILON),
      }
    }
    case 'chapters':
      return chaptersHolding(span.start, span.end, source) ?? defaultOf(kind, source)
  }
}

/** "Whole source", "Chapters 2–3", "0:01:30 – 0:45:00", "Frames 0 – 1440". */
export function rangeLabel(range: Range, t: Translate): string {
  switch (range.kind) {
    case 'full':
      return t('range.label.full')
    case 'chapters':
      return range.start === range.end
        ? t('range.label.chapter', { number: range.start })
        : t('range.label.chapters', { start: range.start, end: range.end })
    case 'time':
      return range.end == null
        ? t('range.label.timeToEnd', { start: formatClock(range.start) })
        : t('range.label.time', { start: formatClock(range.start), end: formatClock(range.end) })
    case 'frames':
      return range.end == null
        ? t('range.label.framesToEnd', { start: range.start })
        : t('range.label.frames', { start: range.start, end: range.end })
  }
}
