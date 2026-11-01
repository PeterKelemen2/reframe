import type { ImportedChapter, OutputChapter } from '@/api/types'

/** Where a chapter's name is in `ChapterSettings.names`. */
export function nameSlot(chapter: OutputChapter): number {
  return chapter.source_index ?? chapter.number - 1
}

/**
 * The name the table shows. The job's names come first: the server's answer can be older than
 * the last edit or undo.
 */
export function shownName(chapter: OutputChapter, names: readonly string[] | null): string {
  const written = names?.[nameSlot(chapter)]
  if (written) return written
  if (chapter.source_index !== null && chapter.source_name) return chapter.source_name
  return chapter.name
}

/**
 * The names list with `changes` (slot → name). Every chapter of the output is written out as the
 * table shows it, so that a change of one name keeps the others.
 */
export function namesWith(
  current: readonly string[] | null,
  chapters: readonly OutputChapter[],
  changes: ReadonlyMap<number, string>,
): string[] {
  const length = Math.max(current?.length ?? 0, ...chapters.map((chapter) => nameSlot(chapter) + 1))
  const names = Array.from({ length }, (_, index) => current?.[index] ?? '')
  for (const chapter of chapters) names[nameSlot(chapter)] = shownName(chapter, current)
  for (const [slot, name] of changes) names[slot] = name
  return names
}

/** `label(1)`, `label(2)`, … for the output's chapters, by their place in the output. */
export function numberedNames(
  current: readonly string[] | null,
  chapters: readonly OutputChapter[],
  label: (number: number) => string,
): string[] {
  return namesWith(
    current,
    chapters,
    new Map(chapters.map((chapter) => [nameSlot(chapter), label(chapter.number)])),
  )
}

/** Seconds: a start in a chapter file this close to the output's counts as the same. */
export const START_TOLERANCE = 0.01

export interface ImportPlan {
  /** Slot → name, for the output's chapters the file has a name for. */
  changes: Map<number, string>
  fileCount: number
  outputCount: number
  /** Chapters whose start in the file differs from the output's. */
  moved: { number: number; file: number; output: number }[]
}

/** The file's names by position over the output's chapters, and where the two differ. */
export function importPlan(
  imported: readonly ImportedChapter[],
  chapters: readonly OutputChapter[],
): ImportPlan {
  const changes = new Map<number, string>()
  const moved: ImportPlan['moved'] = []
  chapters.forEach((chapter, index) => {
    const entry = imported[index]
    if (entry === undefined) return
    changes.set(nameSlot(chapter), entry.name)
    if (entry.start !== null && Math.abs(entry.start - chapter.start) > START_TOLERANCE) {
      moved.push({ number: chapter.number, file: entry.start, output: chapter.start })
    }
  })
  return { changes, fileCount: imported.length, outputCount: chapters.length, moved }
}

/** `H:MM:SS.mmm`. */
export function formatTime(seconds: number): string {
  const total = Math.max(0, Math.round(seconds * 1000))
  const ms = String(total % 1000).padStart(3, '0')
  const secs = String(Math.floor(total / 1000) % 60).padStart(2, '0')
  const minutes = String(Math.floor(total / 60_000) % 60).padStart(2, '0')
  const hours = Math.floor(total / 3_600_000)
  return `${hours}:${minutes}:${secs}.${ms}`
}
