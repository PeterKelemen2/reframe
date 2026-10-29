import type { Schemas } from '@/api/types'

export type NameSpan = Schemas['NameSpan']

/** The colour groups of the parsed-name panel. */
export type SpanTone =
  | 'title'
  | 'episode'
  | 'subtitle'
  | 'year'
  | 'resolution'
  | 'source'
  | 'edition'
  | 'group'
  | 'other'

const TONES: Record<string, SpanTone> = {
  name: 'title',
  main_title: 'title',
  title: 'title',
  episode_code: 'episode',
  season: 'episode',
  episode: 'episode',
  sub_title: 'subtitle',
  episode_title: 'subtitle',
  year: 'year',
  resolution: 'resolution',
  screen_size: 'resolution',
  source_type: 'source',
  source: 'source',
  edition: 'edition',
  release_group: 'group',
}

/** Every other guessit property (codecs, HDR, language, `other`) is one "other tag" tone. */
export function toneOf(field: string): SpanTone {
  return TONES[field] ?? 'other'
}

export interface Segment {
  text: string
  /** `null`: text between the recognised parts (separators, unknown words). */
  span: NameSpan | null
}

/**
 * `text` cut into recognised parts and the text between them. guessit can give two properties
 * for the same characters (`HEVC` as codec and profile): the first one that starts there wins.
 * Positions count code points, as Python's do.
 */
export function segments(text: string, spans: NameSpan[]): Segment[] {
  const chars = Array.from(text)
  const slice = (from: number, to?: number) => chars.slice(from, to).join('')
  const sorted = spans
    .filter((span) => span.start >= 0 && span.end <= chars.length && span.end > span.start)
    .toSorted((a, b) => a.start - b.start || b.end - a.end)
  const result: Segment[] = []
  let at = 0
  for (const span of sorted) {
    if (span.start < at) continue
    if (span.start > at) result.push({ text: slice(at, span.start), span: null })
    result.push({ text: slice(span.start, span.end), span })
    at = span.end
  }
  if (at < chars.length) result.push({ text: slice(at), span: null })
  return result
}
