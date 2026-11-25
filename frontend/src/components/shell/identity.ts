import type { Schemas } from '@/api/types'

import { fileName } from './format'

/** What names a job in one line: `The Sopranos · S03E02 · MKV`, `Heat · MKV`. */
export interface JobIdentityParts {
  /** The show or film name; the file's own name when none was recognised. */
  title: string
  season?: number | null
  episode?: number | null
  /** The output container as the app labels it (`MKV`). */
  container?: string | null
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

/** `S03E02`, `E1071` for an absolute number without a season; `null` without an episode. */
export function episodeCode(
  season: number | null | undefined,
  episode: number | null | undefined,
): string | null {
  if (episode === null || episode === undefined) return null
  return season === null || season === undefined
    ? `E${pad(episode)}`
    : `S${pad(season)}E${pad(episode)}`
}

/** The job's identity line: title, episode code and container, each one only when known. */
export function jobIdentity(parts: JobIdentityParts): string {
  return [parts.title, episodeCode(parts.season, parts.episode), parts.container]
    .filter((part): part is string => typeof part === 'string' && part.trim() !== '')
    .join(' · ')
}

/** A file name without its extension. */
function stem(path: string): string {
  const name = fileName(path)
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(0, dot) : name
}

/**
 * The parts from a parsed name (`jobs/draft`'s `naming.fields`), the source's path and the
 * output container id: the parsed show or film name with spaces between its words (`Anime.Show`
 * reads `Anime Show`), else the file name without its extension; the container as `MKV`.
 */
export function identityParts(
  fields: Schemas['ParsedName'] | null | undefined,
  path: string,
  container: string | null | undefined,
): JobIdentityParts {
  const parsed = fields?.name?.trim() || fields?.main_title?.trim() || ''
  const separator = fields?.separator
  const title =
    parsed === ''
      ? stem(path)
      : separator && separator !== ' '
        ? parsed.split(separator).join(' ').replace(/\s+/g, ' ').trim()
        : parsed
  return {
    title,
    season: fields?.season,
    episode: fields?.episode,
    container: container ? container.toUpperCase() : null,
  }
}
