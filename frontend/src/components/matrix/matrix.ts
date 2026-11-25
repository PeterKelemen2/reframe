import { Check, EqualApproximately, Minus, TriangleAlert, X } from '@lucide/vue'
import type { Component } from 'vue'

import type {
  AudioStream,
  GroupMember,
  JsonPatchOp,
  MatrixColumn,
  Resolution,
  Severity,
  SubtitleStream,
  TrackMatch,
} from '@/api/types'
import { channelsText, streamLanguage } from '@/components/media/streams'
import { fileName } from '@/components/shell/format'
import { episodeLabels } from '@/components/sources/panel'

/** A cell's mark, as `reframe batch` prints it. */
export const MATCH_MARK: Record<TrackMatch['status'], string> = {
  exact: '✓',
  relaxed: '≈',
  ambiguous: '≈',
  missing: '✗',
  skipped: '–',
}

export const ROW_MARK: Record<Resolution['status'], string> = { ok: '✓', warning: '⚠', error: '✗' }

/** The drawn icons of the marks; the glyph stays in `data-mark` for tests and the CLI's words. */
export const MATCH_ICON: Record<TrackMatch['status'], Component> = {
  exact: Check,
  relaxed: EqualApproximately,
  ambiguous: EqualApproximately,
  missing: X,
  skipped: Minus,
}

export const ROW_ICON: Record<Resolution['status'], Component> = {
  ok: Check,
  warning: TriangleAlert,
  error: X,
}

/** The parsed-name fields the naming column shows and edits. */
export const NAME_FIELDS = ['name', 'season', 'episode', 'sub_title', 'year'] as const
export type NameField = (typeof NAME_FIELDS)[number]

export function matchOf(row: Resolution, column: MatrixColumn): TrackMatch | undefined {
  return row.matches?.find((match) => match.kind === column.kind && match.rule === column.rule)
}

/** Row labels as the sources panel has them; a file that is no member is named by its file. */
export function rowLabels(rows: readonly Resolution[], members: readonly GroupMember[]): string[] {
  const labels = episodeLabels(members)
  const byPath = new Map(members.map((member, index) => [member.path, labels[index]]))
  return rows.map((row) => byPath.get(row.path) ?? fileName(row.path))
}

const RANK: Record<Severity, number> = { error: 0, warning: 1, info: 2 }
const NO_PROBLEM = 3

/** Issues of the output name: collisions and an existing output are checked on `output.path`. */
export function nameIssues(row: Resolution) {
  return (row.issues ?? []).filter((issue) => issue.path.startsWith('output'))
}

/** How bad a cell is, for sorting: an error first, then a warning, then the rest. */
export function cellRank(row: Resolution, column: MatrixColumn): number {
  if (row.job == null) return RANK.error
  if (column.kind === 'name') {
    return Math.min(NO_PROBLEM, ...nameIssues(row).map((issue) => RANK[issue.severity]))
  }
  if (column.kind === 'video') return NO_PROBLEM
  const severity = matchOf(row, column)?.severity
  return severity == null ? NO_PROBLEM : RANK[severity]
}

/**
 * The rows sorted by one column's status (`column` an index into the columns), or in episode
 * order (`null`); rows of one status keep their episode order.
 */
export function sortRows<T extends { row: Resolution }>(
  rows: readonly T[],
  columns: readonly MatrixColumn[],
  column: number | null,
  order: 1 | -1,
): T[] {
  const sorting = column === null ? undefined : columns[column]
  if (sorting === undefined) return order === 1 ? [...rows] : rows.toReversed()
  return rows.toSorted((a, b) => order * (cellRank(a.row, sorting) - cellRank(b.row, sorting)))
}

/** The file's override picks the track of this rule by hand (or no track). */
export function pickedByHand(
  override: readonly JsonPatchOp[] | undefined,
  kind: 'audio' | 'subtitle',
  rule: number,
): boolean {
  const selector = `/${kind}_rules/${rule}/selector`
  return (override ?? []).some((op) => op.path === selector || op.path.startsWith(`${selector}/`))
}

/** `#2 · eng · DTS-HD MA 5.1 · English Dub`: a track by its absolute stream index. */
export function trackText(stream: AudioStream | SubtitleStream): string {
  const codec = stream.display_codec || stream.codec || null
  const format =
    stream.kind === 'audio' ? [codec, channelsText(stream)].filter(Boolean).join(' ') : codec
  return [`#${stream.index}`, streamLanguage(stream) ?? 'und', format, stream.title]
    .filter((part) => part !== null && part !== undefined && part !== '')
    .join(' · ')
}
