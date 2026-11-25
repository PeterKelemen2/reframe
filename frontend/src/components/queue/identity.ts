import type { QueueJob } from '@/api/types'
import { fileName } from '@/components/shell/format'
import { episodeCode, type JobIdentityParts, jobIdentity } from '@/components/shell/identity'

const EPISODE = /(?:^|[\s._-])s(\d{1,2})[\s._-]?e(\d{1,3})(?:-?e\d{1,3})*(?=$|[\s._-])/i
const CROSS = /(?:^|[\s._-])(\d{1,2})x(\d{2,3})(?=$|[\s._-])/i
/** Where a release name's technical part starts: the title is the words before it. */
const RELEASE_TAG =
  /^(?:\d{3,4}[pi]|4k|uhd|blu-?ray|bdrip|brrip|remux|web-?dl|web-?rip|web|hdtv|dvdrip|x26[45]|h\.?26[45]|hevc|avc|av1|hdr\d*|dv|10bit|proper|repack)$/i

function stem(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(0, dot) : name
}

/** A release name's words: dots and underscores are spaces unless the name has real spaces. */
function words(text: string): string {
  const spaced = /\s/.test(text) ? text : text.replace(/[._]+/g, ' ')
  return spaced.replace(/\s+/g, ' ').trim()
}

function cleanTitle(text: string): string {
  return words(text)
    .replace(/[\s\-–·]+$/u, '')
    .replace(/^[\s\-–·]+/u, '')
}

function titleWithoutTags(text: string): string {
  const parts = words(text).split(' ')
  const cut = parts.findIndex((part, index) => index > 0 && RELEASE_TAG.test(part))
  return (cut > 0 ? parts.slice(0, cut) : parts).join(' ').replace(/[\s\-–]+$/u, '')
}

/**
 * The title, season and episode of a source file name (`The.Sopranos.S03E02.Proshai.mkv`): a
 * queued job carries its file name, not the parsed name the editor has.
 */
function parseName(name: string): Omit<JobIdentityParts, 'container'> {
  const base = stem(fileName(name))
  const found = EPISODE.exec(base) ?? CROSS.exec(base)
  if (found !== null && found[1] !== undefined && found[2] !== undefined) {
    const title = cleanTitle(base.slice(0, found.index))
    const [season, episode] = [Number(found[1]), Number(found[2])]
    return title ? { title, season, episode } : { title: episodeCode(season, episode) ?? base }
  }
  return { title: titleWithoutTags(base) || base }
}

/** The title and episode label of a source file name. */
export function parseFileName(name: string): { title: string; episode: string | null } {
  const { title, season, episode } = parseName(name)
  return { title, episode: episodeCode(season, episode) }
}

function containerOf(job: QueueJob): string | null {
  const chosen = job.settings.output?.container
  if (chosen) return chosen.toUpperCase()
  const output = job.output_path || job.settings.output?.path
  const extension = output ? /\.([a-z0-9]{2,4})$/i.exec(output)?.[1] : undefined
  return extension ? extension.toUpperCase() : null
}

/** `The Sopranos · S03E02 · MKV`, as the status bar names the job; a film: `Heat (1995) · MKV`. */
export function identityLine(job: QueueJob): string {
  return jobIdentity({ ...parseName(job.settings.source.path), container: containerOf(job) })
}
