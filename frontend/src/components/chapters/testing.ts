// Test data shaped as the server's `jobs/chapters` answers for testdata's chapters.mkv
// (Opening 0–1 s, Part One 1–2.5 s, Part Two 2.5–4 s).
import type { JobSettings, OutputChapter, OutputChapters } from '@/api/types'

export const SOURCE_NAMES = ['Opening', 'Part One', 'Part Two']
const TIMES: [number, number][] = [
  [0, 1],
  [1, 2.5],
  [2.5, 4],
]

export function chapter(
  number: number,
  start: number,
  end: number,
  name: string,
  sourceIndex: number | null = number - 1,
): OutputChapter {
  return {
    number,
    start,
    end,
    name,
    source_name: sourceIndex === null ? null : (SOURCE_NAMES[sourceIndex] ?? null),
    source_index: sourceIndex,
  }
}

/** The output's chapters as the core makes them for the job's chapter settings. */
export function chaptersOf(job: JobSettings): OutputChapters {
  const settings = job.chapters
  if (settings?.enabled === false) {
    return { origin: 'none', chapters: [], reason: 'Create chapter markers is off.' }
  }
  return {
    origin: 'source',
    reason: '',
    chapters: TIMES.map(([start, end], index) =>
      chapter(index + 1, start, end, settings?.names?.[index] || (SOURCE_NAMES[index] as string)),
    ),
  }
}
