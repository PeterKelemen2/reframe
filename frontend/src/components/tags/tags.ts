import type { RenderedTags, TagName } from '@/api/types'

/** The eight tags, in HandBrake's order. */
export const TAG_NAMES: readonly TagName[] = [
  'title',
  'actors',
  'director',
  'release_date',
  'comment',
  'genre',
  'description',
  'plot',
]

export type WrittenValue =
  | { kind: 'unknown' }
  | { kind: 'value'; text: string }
  /** Not set: *Passthru common metadata* copies the source's value. */
  | { kind: 'copied'; text: string }
  | { kind: 'none' }

/** What the output gets for `name`. */
export function writtenValue(
  rendered: RenderedTags | null,
  name: TagName,
  passthru: boolean,
): WrittenValue {
  if (rendered === null) return { kind: 'unknown' }
  const value = rendered.values[name]
  if (value !== null) return { kind: 'value', text: value }
  const source = rendered.source[name]
  return passthru && source !== null ? { kind: 'copied', text: source } : { kind: 'none' }
}
