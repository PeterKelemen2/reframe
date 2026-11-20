import type {
  AudioStream,
  Definitions,
  JobSettings,
  MediaSource,
  SubtitleStream,
  TrackRoleInfo,
} from '@/api/types'
import { fileName } from '@/components/shell/format'

export const FLAGS = [
  'default',
  'forced',
  'commentary',
  'hearing_impaired',
  'visual_impaired',
  'original',
] as const
export type Flag = (typeof FLAGS)[number]

const CONVERTED: Record<string, string> = {
  srt: 'SRT',
  ass: 'ASS',
  webvtt: 'WebVTT',
  mov_text: 'mov_text',
}

interface TrackChip {
  /** The validation path of the output track (`audio[1]`): the chip reveals it. */
  path: string
  language: string | null
  name: string | null
  roles: TrackRoleInfo[]
  flags: Flag[]
}

export interface AudioChip extends TrackChip {
  stream: AudioStream | undefined
  passthru: boolean
  /** The encoder's name; `null` for a copied track. */
  encoder: string | null
  /** The mixdown, or the source's layout when it is kept. */
  layout: string | null
}

export interface SubtitleChip extends TrackChip {
  stream: SubtitleStream | undefined
  action: 'copy' | 'burn' | 'convert'
  /** The file name of an external subtitle. */
  external: string | null
  /** The format a converted track gets. */
  convertTo: string | null
}

/** The output flags that a role badge set by the source's disposition already names. */
const FLAGS_OF_ROLE: Partial<Record<TrackRoleInfo['role'], readonly Flag[]>> = {
  commentary: ['commentary'],
  sdh: ['hearing_impaired'],
  forced: ['forced'],
  description: ['visual_impaired'],
}

function flagsOf(
  metadata: Partial<Record<Flag, boolean>> | undefined,
  roles: readonly TrackRoleInfo[],
): Flag[] {
  const named = new Set<Flag>()
  for (const role of roles) {
    if (role.evidence === 'flag') for (const flag of FLAGS_OF_ROLE[role.role] ?? []) named.add(flag)
  }
  return FLAGS.filter((flag) => metadata?.[flag] === true && !named.has(flag))
}

function layoutOf(stream: AudioStream | undefined): string | null {
  if (stream === undefined) return null
  return stream.channel_layout ?? (stream.channels > 0 ? String(stream.channels) : null)
}

/**
 * The names the job writes when the server filled in their templates and they are for these
 * tracks; else the job's own names.
 */
function namesOf(
  tracks: readonly { metadata?: { name?: string | null } }[],
  written: readonly (string | null)[] | undefined,
): (string | null | undefined)[] {
  if (written !== undefined && written.length === tracks.length) return [...written]
  return tracks.map((track) => track.metadata?.name)
}

export function audioChips(
  job: JobSettings,
  source: MediaSource | null,
  definitions: Definitions | null,
  written?: readonly (string | null)[],
): AudioChip[] {
  const names = namesOf(job.audio ?? [], written)
  return (job.audio ?? []).map((track, index) => {
    const stream = source?.audio?.find((candidate) => candidate.index === track.source_stream)
    const passthru = track.action === 'passthru'
    const mixdown = track.mixdown
      ? (definitions?.mixdowns?.[track.mixdown]?.label ?? track.mixdown)
      : null
    return {
      path: `audio[${index}]`,
      language: track.metadata?.language ?? stream?.language ?? null,
      name: names[index] ?? stream?.title ?? null,
      roles: stream?.roles ?? [],
      flags: flagsOf(track.metadata, stream?.roles ?? []),
      stream,
      passthru,
      encoder:
        passthru || track.encoder === null
          ? null
          : (definitions?.audio_encoders?.[track.encoder]?.label ?? track.encoder),
      layout: passthru ? layoutOf(stream) : (mixdown ?? layoutOf(stream)),
    }
  })
}

export function subtitleChips(
  job: JobSettings,
  source: MediaSource | null,
  written?: readonly (string | null)[],
): SubtitleChip[] {
  const names = namesOf(job.subtitles ?? [], written)
  return (job.subtitles ?? []).map((track, index) => {
    const external = typeof track.source === 'object' ? track.source : null
    const stream =
      external === null
        ? source?.subtitles?.find((candidate) => candidate.index === track.source)
        : undefined
    return {
      path: `subtitles[${index}]`,
      language: track.metadata?.language ?? stream?.language ?? external?.language ?? null,
      name: names[index] ?? stream?.title ?? external?.name ?? null,
      roles: stream?.roles ?? [],
      flags: flagsOf(track.metadata, stream?.roles ?? []),
      stream,
      action: track.action,
      external: external === null ? null : fileName(external.path),
      convertTo:
        track.action === 'convert' && track.convert_to
          ? (CONVERTED[track.convert_to] ?? track.convert_to)
          : null,
    }
  })
}
