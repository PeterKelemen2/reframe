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

function flagsOf(metadata: Partial<Record<Flag, boolean>> | undefined): Flag[] {
  return FLAGS.filter((flag) => metadata?.[flag] === true)
}

function layoutOf(stream: AudioStream | undefined): string | null {
  if (stream === undefined) return null
  return stream.channel_layout ?? (stream.channels > 0 ? String(stream.channels) : null)
}

export function audioChips(
  job: JobSettings,
  source: MediaSource | null,
  definitions: Definitions | null,
): AudioChip[] {
  return (job.audio ?? []).map((track, index) => {
    const stream = source?.audio?.find((candidate) => candidate.index === track.source_stream)
    const passthru = track.action === 'passthru'
    const mixdown = track.mixdown
      ? (definitions?.mixdowns?.[track.mixdown]?.label ?? track.mixdown)
      : null
    return {
      path: `audio[${index}]`,
      language: track.metadata?.language ?? stream?.language ?? null,
      name: track.metadata?.name ?? stream?.title ?? null,
      roles: stream?.roles ?? [],
      flags: flagsOf(track.metadata),
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

export function subtitleChips(job: JobSettings, source: MediaSource | null): SubtitleChip[] {
  return (job.subtitles ?? []).map((track, index) => {
    const external = typeof track.source === 'object' ? track.source : null
    const stream =
      external === null
        ? source?.subtitles?.find((candidate) => candidate.index === track.source)
        : undefined
    return {
      path: `subtitles[${index}]`,
      language: track.metadata?.language ?? stream?.language ?? external?.language ?? null,
      name: track.metadata?.name ?? stream?.title ?? external?.name ?? null,
      roles: stream?.roles ?? [],
      flags: flagsOf(track.metadata),
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
