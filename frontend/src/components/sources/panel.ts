import type { Schemas, SourceEntry } from '@/api/types'
import { fileName, formatDuration } from '@/components/shell/format'

type BatchGroup = Schemas['BatchGroup']
type GroupMember = Schemas['GroupMember']

export interface GroupRow {
  entry: SourceEntry
  member: GroupMember
  /** `E05`, `S01E05` when the group spans seasons, else the file name. */
  label: string
}

export type PanelItem =
  | { kind: 'source'; entry: SourceEntry }
  | { kind: 'group'; group: BatchGroup; rows: GroupRow[] }

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/**
 * Labels as the batch engine prints them: a file without an episode, and files that would share
 * a label (two releases of one episode), are named by their file name.
 */
export function episodeLabels(members: readonly GroupMember[]): string[] {
  const seasons = new Set(
    members.filter((member) => member.episode != null).map((member) => member.season ?? null),
  )
  const withSeason = seasons.size > 1
  const labels = members.map((member) => {
    if (member.episode == null) return fileName(member.path)
    if (withSeason && member.season != null) return `S${pad(member.season)}E${pad(member.episode)}`
    return `E${pad(member.episode)}`
  })
  const counts = new Map<string, number>()
  for (const label of labels) counts.set(label, (counts.get(label) ?? 0) + 1)
  return labels.map((label, index) =>
    counts.get(label) === 1 ? label : fileName(members[index]?.path ?? label),
  )
}

/**
 * The panel's rows in the order the sources were opened: a group of two or more open sources
 * takes the place of its first one; the other sources stand alone. A stale grouping is harmless:
 * members that are not open are left out.
 */
export function panelItems(
  entries: readonly SourceEntry[],
  grouping: Schemas['BatchGrouping'] | null,
): PanelItem[] {
  const byPath = new Map(entries.map((entry) => [entry.path, entry]))
  const groupOf = new Map<string, PanelItem>()
  for (const group of grouping?.groups ?? []) {
    const open = (group.members ?? []).flatMap((member) => {
      const entry = byPath.get(member.path)
      return entry === undefined || groupOf.has(entry.id) ? [] : [{ entry, member }]
    })
    if (open.length < 2) continue
    const labels = episodeLabels(open.map(({ member }) => member))
    const item: PanelItem = {
      kind: 'group',
      group,
      rows: open.map((row, index) => ({ ...row, label: labels[index] ?? '' })),
    }
    for (const { entry } of open) groupOf.set(entry.id, item)
  }
  const items: PanelItem[] = []
  const placed = new Set<PanelItem>()
  for (const entry of entries) {
    const item = groupOf.get(entry.id)
    if (item === undefined) items.push({ kind: 'source', entry })
    else if (!placed.has(item)) {
      placed.add(item)
      items.push(item)
    }
  }
  return items
}

/** The short line under a source's name: container, duration, video (codec and size). */
export function sourceSummary(entry: SourceEntry): string[] {
  const source = entry.source
  if (source === null) return []
  const parts: string[] = []
  const container = source.container?.display_name
  if (container) parts.push(container)
  const duration = formatDuration(source.container?.duration)
  if (duration !== null) parts.push(duration)
  const video = source.video?.[0]
  if (video !== undefined) {
    const codec = video.display_codec ?? video.codec ?? null
    parts.push([codec, `${video.width}×${video.height}`].filter(Boolean).join(' '))
  }
  return parts
}
