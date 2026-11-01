import { reactive } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, ApiError, apiQuiet, unwrap } from '@/api/client'
import type { SubtitleFileInfo } from '@/api/types'
import { platform } from '@/platform'

/** The subtitle files a job can take. */
export const SUBTITLE_FILE_FILTERS = ['.srt', '.ass', '.ssa', '.vtt', '.sup']

/** What `subtitles/inspect` said about a file; `null`: it could not be read. */
type Inspected = SubtitleFileInfo | null

/** Inspection answers by path, kept for the page: a row shows them again after an undo. */
const answers = reactive(new Map<string, Inspected>())
const asked = new Map<string, Promise<Inspected>>()

export function inspected(path: string): Inspected | undefined {
  return answers.get(path)
}

/**
 * Inspects a file once per path (`POST /api/subtitles/inspect`). `quiet`: a refusal is not
 * toasted, for a row that asks on its own; a file the user picked shows it.
 */
export function inspect(path: string, options: { quiet?: boolean } = {}): Promise<Inspected> {
  const running = asked.get(path)
  if (running !== undefined) return running
  const client = options.quiet ? apiQuiet : api
  const request = (async () => {
    try {
      const info = unwrap(await client.POST('/api/subtitles/inspect', { body: { path } }))
      answers.set(path, info)
      // The track keeps the server's spelling of the path, which the row looks up.
      answers.set(info.path, info)
      return info
    } catch (error) {
      if (!(error instanceof ApiError)) throw error
      answers.set(path, null)
      return null
    } finally {
      asked.delete(path)
    }
  })()
  asked.set(path, request)
  return request
}

/** The subtitle files the user picks, each inspected; the ones that were refused are left out. */
export async function pickSubtitleFiles(): Promise<SubtitleFileInfo[]> {
  const paths = await platform.pickFiles({ multiple: true, filters: SUBTITLE_FILE_FILTERS })
  const infos = await Promise.all(paths.map((path) => inspect(path)))
  return infos.filter((info): info is SubtitleFileInfo => info !== null)
}

/** Forgets every answer (tests). */
export function forgetInspected(): void {
  answers.clear()
  asked.clear()
}

/** `SRT` for `subrip` or `srt`, `PGS` for `hdmv_pgs_subtitle`; an unknown codec as it is. */
export function useSubtitleFormatName(): (format: string) => string {
  const { t, te } = useI18n()
  return (format) => {
    const key = `tracks.external.formatNames.${format}`
    return te(key) ? t(key) : format
  }
}
