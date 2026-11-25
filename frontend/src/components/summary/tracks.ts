import type {
  AudioStream,
  Definitions,
  JobSettings,
  MediaSource,
  SubtitleStream,
  TrackRoleInfo,
} from '@/api/types'
import { channelsText } from '@/components/media/streams'
import { fileName } from '@/components/shell/format'
import { canCopy, containerDef, DEFAULT_AUDIO_ENCODER } from '@/components/tracks/ops'

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
  /** The source's title when the track is written with another name. */
  sourceName: string | null
  roles: TrackRoleInfo[]
  flags: Flag[]
}

export interface AudioChip extends TrackChip {
  stream: AudioStream | undefined
  /** Copied as it is: passthru that the container holds. */
  passthru: boolean
  /** The encoder's name; `null` for a copied track. */
  encoder: string | null
  /** The mixdown, or the source's layout when it is kept. */
  layout: string | null
  /** The source's codec and layout (`DTS-HD MA 5.1`) when the track is written with others. */
  from: string | null
}

export interface SubtitleChip extends TrackChip {
  stream: SubtitleStream | undefined
  action: 'copy' | 'burn' | 'convert'
  /** The file name of an external subtitle. */
  external: string | null
  /** The format a converted track gets, also on a copy that the container converts. */
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

/** The title the source had, when the track is written with another one. */
function renamedFrom(name: string | null, title: string | null | undefined): string | null {
  return title && name !== title ? title : null
}

/**
 * Whether a passthru track is copied. Without the container's codecs it counts as copied.
 */
function copies(
  job: JobSettings,
  stream: AudioStream | undefined,
  definitions: Definitions | null,
): boolean {
  const support = containerDef(definitions, job.output?.container)?.audio
  return support === undefined || stream === undefined || canCopy(support, stream.codec)
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
    const passthru = track.action === 'passthru' && copies(job, stream, definitions)
    const encoderId = track.encoder ?? DEFAULT_AUDIO_ENCODER
    const encoder = definitions?.audio_encoders?.[encoderId]
    const mixdown = track.mixdown ? definitions?.mixdowns?.[track.mixdown] : undefined
    const sourceChannels = stream?.channels ?? 0
    // A mixdown never upmixes: a source with fewer channels keeps its layout.
    const upmix = mixdown !== undefined && sourceChannels > 0 && mixdown.channels > sourceChannels
    const mixdownLabel = track.mixdown && !upmix ? (mixdown?.label ?? track.mixdown) : null
    const channels = mixdown !== undefined && !upmix ? mixdown.channels : sourceChannels
    const changed =
      !passthru &&
      encoder !== undefined &&
      stream !== undefined &&
      (encoder.codec !== stream.codec || channels !== stream.channels)
    const name = names[index] ?? stream?.title ?? null
    return {
      path: `audio[${index}]`,
      language: track.metadata?.language ?? stream?.language ?? null,
      name,
      sourceName: renamedFrom(name, stream?.title),
      roles: stream?.roles ?? [],
      flags: flagsOf(track.metadata, stream?.roles ?? []),
      stream,
      passthru,
      encoder: passthru ? null : (encoder?.label ?? encoderId),
      layout: passthru ? layoutOf(stream) : (mixdownLabel ?? layoutOf(stream)),
      from: changed
        ? [stream.display_codec || stream.codec, channelsText(stream)].filter(Boolean).join(' ')
        : null,
    }
  })
}

/** The format a track is written in when it is not its source's; `null` when it is kept. */
function writtenFormat(
  job: JobSettings,
  track: NonNullable<JobSettings['subtitles']>[number],
  stream: SubtitleStream | undefined,
  definitions: Definitions | null,
): string | null {
  if (track.action === 'convert') return track.convert_to ?? null
  if (track.action !== 'copy' || stream === undefined || stream.subtitle_kind === 'bitmap') {
    return null
  }
  const container = containerDef(definitions, job.output?.container)
  if (container?.subtitles === undefined || canCopy(container.subtitles, stream.codec)) return null
  return container.text_subtitle_target ?? null
}

export function subtitleChips(
  job: JobSettings,
  source: MediaSource | null,
  written?: readonly (string | null)[],
  definitions: Definitions | null = null,
): SubtitleChip[] {
  const names = namesOf(job.subtitles ?? [], written)
  return (job.subtitles ?? []).map((track, index) => {
    const external = typeof track.source === 'object' ? track.source : null
    const stream =
      external === null
        ? source?.subtitles?.find((candidate) => candidate.index === track.source)
        : undefined
    const format = writtenFormat(job, track, stream, definitions)
    const title = stream?.title ?? external?.name
    const name = names[index] ?? title ?? null
    return {
      path: `subtitles[${index}]`,
      language: track.metadata?.language ?? stream?.language ?? external?.language ?? null,
      name,
      sourceName: track.action === 'burn' ? null : renamedFrom(name, title),
      roles: stream?.roles ?? [],
      flags: flagsOf(track.metadata, stream?.roles ?? []),
      stream,
      action: track.action,
      external: external === null ? null : fileName(external.path),
      convertTo: format === null ? null : (CONVERTED[format] ?? format),
    }
  })
}
