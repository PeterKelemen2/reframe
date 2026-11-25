import type { QueueJob } from '@/api/types'
import { fileName } from '@/components/shell/format'

/** A job's title, episode label and container, as the identity line shows them. */
export interface JobIdentity {
  title: string
  /** `S03E02`; `null` for a file without an episode. */
  episode: string | null
  /** `MKV`; `null` when neither the settings nor the output name tell it. */
  container: string | null
}

const EPISODE = /(?:^|[\s._-])s(\d{1,2})[\s._-]?e(\d{1,3})(?:-?e\d{1,3})*(?=$|[\s._-])/i
const CROSS = /(?:^|[\s._-])(\d{1,2})x(\d{2,3})(?=$|[\s._-])/i
/** Where a release name's technical part starts: the title is the words before it. */
const RELEASE_TAG =
  /^(?:\d{3,4}[pi]|4k|uhd|blu-?ray|bdrip|brrip|remux|web-?dl|web-?rip|web|hdtv|dvdrip|x26[45]|h\.?26[45]|hevc|avc|av1|hdr\d*|dv|10bit|proper|repack)$/i

function pad(value: string): string {
  return value.padStart(2, '0')
}

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

/** The title and episode of a source file name (`The.Sopranos.S03E02.Proshai.mkv`). */
export function parseFileName(name: string): { title: string; episode: string | null } {
  const base = stem(fileName(name))
  const found = EPISODE.exec(base) ?? CROSS.exec(base)
  if (found !== null && found[1] !== undefined && found[2] !== undefined) {
    const title = cleanTitle(base.slice(0, found.index))
    const episode = `S${pad(found[1])}E${pad(found[2])}`
    return { title: title || episode, episode: title ? episode : null }
  }
  return { title: titleWithoutTags(base) || base, episode: null }
}

function containerOf(job: QueueJob): string | null {
  const chosen = job.settings.output?.container
  if (chosen) return chosen.toUpperCase()
  const output = job.output_path || job.settings.output?.path
  const extension = output ? /\.([a-z0-9]{2,4})$/i.exec(output)?.[1] : undefined
  return extension ? extension.toUpperCase() : null
}

export function jobIdentity(job: QueueJob): JobIdentity {
  const { title, episode } = parseFileName(job.settings.source.path)
  return { title, episode, container: containerOf(job) }
}

/** `The Sopranos · S03E02 · MKV`; a file without an episode: `Heat (1995) · MKV`. */
export function identityLine(job: QueueJob): string {
  const { title, episode, container } = jobIdentity(job)
  return [title, episode, container].filter((part) => part !== null && part !== '').join(' · ')
}
