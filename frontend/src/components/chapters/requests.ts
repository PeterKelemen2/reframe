import { apiQuiet, unwrap } from '@/api/client'
import type {
  ChapterExport,
  ChapterFormat,
  ChapterImport,
  JobSettings,
  OutputChapters,
} from '@/api/types'

/** The chapters the output gets. */
export async function outputChapters(
  job: JobSettings,
  signal?: AbortSignal,
): Promise<OutputChapters> {
  return unwrap(await apiQuiet.POST('/api/jobs/chapters', { body: { job }, signal }))
}

/** Reads a chapter file on the server; `format` `null` lets the server tell it from the content. */
export async function importChapters(
  path: string,
  format: ChapterFormat | null = null,
): Promise<ChapterImport> {
  return unwrap(await apiQuiet.POST('/api/chapters/import', { body: { path, format } }))
}

/** The output's chapters as the text of a chapter file. */
export async function exportChapters(
  job: JobSettings,
  format: ChapterFormat,
): Promise<ChapterExport> {
  return unwrap(await apiQuiet.POST('/api/jobs/chapters/export', { body: { job, format } }))
}
