import { apiQuiet, unwrap } from '@/api/client'
import type {
  ChapterExport,
  ChapterExportRequest,
  ChapterFormat,
  ChapterImport,
  ChapterImportRequest,
  JobSettings,
  OutputChapters,
} from '@/api/types'

// These routes are not in the generated schema yet: the cast stays inside this module.
type Post = (
  path: string,
  init: { body: unknown; signal?: AbortSignal },
) => Promise<{ data?: unknown; error?: unknown; response: Response }>

function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const send = apiQuiet.POST as unknown as Post
  return send(path, { body, signal }).then((result) => unwrap(result) as T)
}

/** The chapters the output gets (`POST /api/jobs/chapters`). */
export function outputChapters(job: JobSettings, signal?: AbortSignal): Promise<OutputChapters> {
  return post('/api/jobs/chapters', { job }, signal)
}

/** Reads a chapter file on the server; `format` `null` lets the server tell it from the content. */
export function importChapters(
  path: string,
  format: ChapterFormat | null = null,
): Promise<ChapterImport> {
  const body: ChapterImportRequest = { path, format }
  return post('/api/chapters/import', body)
}

/** The output's chapters as the text of a chapter file. */
export function exportChapters(job: JobSettings, format: ChapterFormat): Promise<ChapterExport> {
  const body: ChapterExportRequest = { job, format }
  return post('/api/jobs/chapters/export', body)
}
