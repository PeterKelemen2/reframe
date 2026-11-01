import type {
  AudioOutputTrack,
  AudioStream,
  Definitions,
  JobDraft,
  JsonPatchOp,
  Schemas,
  SubtitleOutputTrack,
  SubtitleStream,
} from '@/api/types'
import type { SourceStream } from '@/components/media/streams'

type AudioEncoderDef = Schemas['AudioEncoderDef']
type CodecSupport = Schemas['CodecSupport']
type ContainerDef = Schemas['ContainerDef']
type TrackMetadata = Schemas['TrackMetadata']
export type Mixdown = NonNullable<AudioOutputTrack['mixdown']>
export type SubtitleFormat = NonNullable<SubtitleOutputTrack['convert_to']>
export type TrackList = 'audio' | 'subtitles'

/** The encoder a track uses when it names none (the core's default). */
export const DEFAULT_AUDIO_ENCODER = 'aac'
export const SUBTITLE_FORMATS: readonly SubtitleFormat[] = ['srt', 'ass', 'webvtt', 'mov_text']

/** Bitrates offered for an encoder that does not list its own, in kb/s. */
const BITRATE_LADDER = [
  6, 8, 12, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 448, 512,
  576, 640, 768, 896, 1024, 1280, 1536, 2048,
]

/** What a new track is made from besides its source stream. */
export interface NewTrackContext {
  definitions: Definitions | null
  container: string | undefined
  /** The editor's draft: the preset's own output for a source track, when it gave one. */
  draft: JobDraft | null
  /** An encoder can be used (not missing from the FFmpeg build). */
  usable: (encoder: string) => boolean
}

/** The container's rules: copied codecs (`*` for any) minus the exceptions. */
export function canCopy(
  support: CodecSupport | undefined,
  codec: string | null | undefined,
): boolean {
  if (!support || !codec) return false
  if (support.copy_except?.includes(codec)) return false
  return support.copy?.includes('*') === true || support.copy?.includes(codec) === true
}

export function containerDef(
  definitions: Definitions | null,
  container: string | undefined,
): ContainerDef | undefined {
  return container === undefined ? undefined : definitions?.containers?.[container]
}

/** The source track's language, title and flags; language and title follow the source (`null`). */
export function sourceMetadata(stream: SourceStream): TrackMetadata {
  const d = stream.disposition
  return {
    default: d?.default === true,
    forced: d?.forced === true,
    commentary: d?.comment === true,
    hearing_impaired: d?.hearing_impaired === true,
    visual_impaired: d?.visual_impaired === true,
    original: d?.original === true,
    language: null,
    name: null,
  }
}

/** Only one default track of a kind: a track added beside a default one is not default. */
function withoutSecondDefault<T extends { metadata?: TrackMetadata }>(
  track: T,
  existing: readonly { metadata?: TrackMetadata }[],
): T {
  if (track.metadata?.default !== true || !existing.some((other) => other.metadata?.default)) {
    return track
  }
  return { ...track, metadata: { ...track.metadata, default: false } }
}

/** The first encoder the container takes and the build has, AAC first. */
function fallbackEncoder(context: NewTrackContext): string {
  const encoders = context.definitions?.audio_encoders ?? {}
  const holds = containerDef(context.definitions, context.container)?.audio.encode
  const ids = [DEFAULT_AUDIO_ENCODER, ...Object.keys(encoders)]
  return (
    ids.find((id) => {
      const encoder = encoders[id]
      return encoder !== undefined && (holds?.includes(encoder.codec) ?? true) && context.usable(id)
    }) ?? DEFAULT_AUDIO_ENCODER
  )
}

/** The bitrate table that applies to a track: its mixdown's, or the source layout's. */
export function bitrateTable(
  encoder: AudioEncoderDef | undefined,
  mixdown: Mixdown | null | undefined,
  channels: number,
): Schemas['BitrateLimits'] | null {
  const tables = encoder?.bitrate?.by_mixdown
  if (!tables) return null
  let key: string = mixdown ?? ''
  if (!mixdown) {
    key = channels === 1 ? 'mono' : channels <= 2 ? 'stereo' : channels <= 6 ? '5.1' : '7.1'
  }
  return tables[key] ?? Object.values(tables).at(-1) ?? null
}

/** The bitrates a choice offers: the encoder's list, or common steps, inside the table's range. */
export function bitrateChoices(
  encoder: AudioEncoderDef | undefined,
  limits: Schemas['BitrateLimits'] | null,
  current: number | null | undefined,
): number[] {
  if (!encoder?.bitrate || limits === null) return current ? [current] : []
  const steps = encoder.bitrate.allowed ?? BITRATE_LADDER
  const choices = steps.filter((value) => value >= limits.min && value <= limits.max)
  if (current && !choices.includes(current)) choices.push(current)
  return choices.toSorted((a, b) => a - b)
}

export function newAudioTrack(
  stream: AudioStream,
  existing: readonly AudioOutputTrack[],
  context: NewTrackContext,
): AudioOutputTrack {
  const drafted = context.draft?.decisions?.find(
    (decision) => decision.source_stream === stream.index,
  )?.outputs?.[0]
  if (drafted !== undefined) return withoutSecondDefault(structuredClone(drafted), existing)
  const encoderId = fallbackEncoder(context)
  const encoder = context.definitions?.audio_encoders?.[encoderId]
  const wanted: Mixdown = stream.channels === 1 ? 'mono' : 'stereo'
  const mixdown = !encoder?.mixdowns || encoder.mixdowns.includes(wanted) ? wanted : null
  return withoutSecondDefault(
    {
      action: 'encode',
      encoder: encoderId,
      mixdown,
      samplerate: null,
      bitrate: bitrateTable(encoder, mixdown, stream.channels)?.default ?? null,
      quality: null,
      gain: 0,
      drc: 0,
      loudness: 'off',
      source_stream: stream.index,
      metadata: sourceMetadata(stream),
    },
    existing,
  )
}

export function newSubtitleTrack(
  stream: SubtitleStream,
  existing: readonly SubtitleOutputTrack[],
  context: Pick<NewTrackContext, 'draft'>,
): SubtitleOutputTrack {
  const drafted = context.draft?.subtitle_decisions?.find(
    (decision) => decision.source_stream === stream.index,
  )?.subtitle_outputs?.[0]
  if (drafted !== undefined) return withoutSecondDefault(structuredClone(drafted), existing)
  return withoutSecondDefault(
    {
      action: 'copy',
      convert_to: null,
      forced_only: false,
      source: stream.index,
      metadata: sourceMetadata(stream),
    },
    existing,
  )
}

/** The source stream an output track reads; `null` for an external file or none. */
export function sourceIndex(track: AudioOutputTrack | SubtitleOutputTrack): number | null {
  if ('source' in track) return typeof track.source === 'number' ? track.source : null
  return track.source_stream ?? null
}

/** One `add` per stream (in source order); each new track sees the ones added before it. */
export function addOps<T extends AudioOutputTrack | SubtitleOutputTrack, S extends SourceStream>(
  list: TrackList,
  streams: readonly S[],
  existing: readonly T[],
  make: (stream: S, existing: readonly T[]) => T,
): JsonPatchOp[] {
  const tracks = [...existing]
  return streams.map((stream) => {
    const track = make(stream, tracks)
    tracks.push(track)
    return { op: 'add', path: `/${list}/-`, value: track } as JsonPatchOp
  })
}

/** The source streams that no output track reads yet. */
export function unusedStreams<S extends SourceStream>(
  streams: readonly S[],
  tracks: readonly (AudioOutputTrack | SubtitleOutputTrack)[],
): S[] {
  const used = new Set(tracks.map(sourceIndex))
  return streams.filter((stream) => !used.has(stream.index))
}

export function moveOp(list: TrackList, from: number, to: number): JsonPatchOp {
  return { op: 'move', from: `/${list}/${from}`, path: `/${list}/${to}` } as JsonPatchOp
}

export function removeOp(list: TrackList, index: number): JsonPatchOp {
  return { op: 'remove', path: `/${list}/${index}` } as JsonPatchOp
}

function replace(path: string, value: unknown): JsonPatchOp {
  return { op: 'replace', path, value } as JsonPatchOp
}

/** Another source stream: its metadata comes along, the track keeps its default flag. */
export function sourceChangeOps(
  list: TrackList,
  index: number,
  track: AudioOutputTrack | SubtitleOutputTrack,
  stream: SourceStream,
): JsonPatchOp[] {
  const member = list === 'audio' ? 'source_stream' : 'source'
  const metadata = { ...sourceMetadata(stream), default: track.metadata?.default === true }
  return [
    replace(`/${list}/${index}/${member}`, stream.index),
    replace(`/${list}/${index}/metadata`, metadata),
  ]
}

/** A bitrate the encoder cannot write for the layout becomes its default for that layout. */
function fittedBitrate(
  bitrate: number | null | undefined,
  encoder: AudioEncoderDef | undefined,
  limits: Schemas['BitrateLimits'] | null,
): number | null {
  if (bitrate === null || bitrate === undefined) return null
  if (!encoder?.bitrate || limits === null) return null
  const allowed = encoder.bitrate.allowed
  const fits =
    bitrate >= limits.min && bitrate <= limits.max && (!allowed || allowed.includes(bitrate))
  return fits ? bitrate : limits.default
}

/**
 * Another encoder: a mixdown it cannot make, a bitrate it cannot write and a VBR quality it
 * does not have are changed with it, so the track stays valid.
 */
export function encoderChangeOps(
  index: number,
  track: AudioOutputTrack,
  encoderId: string,
  definitions: Definitions | null,
  channels: number,
): JsonPatchOp[] {
  const base = `/audio/${index}`
  const encoder = definitions?.audio_encoders?.[encoderId]
  const ops = [replace(`${base}/encoder`, encoderId)]
  let mixdown = track.mixdown ?? null
  if (mixdown !== null && encoder?.mixdowns && !encoder.mixdowns.includes(mixdown)) {
    mixdown = encoder.mixdowns.includes('stereo') ? 'stereo' : (encoder.mixdowns[0] ?? null)
    ops.push(replace(`${base}/mixdown`, mixdown))
  }
  const bitrate = fittedBitrate(track.bitrate, encoder, bitrateTable(encoder, mixdown, channels))
  if (bitrate !== (track.bitrate ?? null)) ops.push(replace(`${base}/bitrate`, bitrate))
  if (track.quality !== null && track.quality !== undefined && !encoder?.quality) {
    ops.push(replace(`${base}/quality`, null))
  }
  return ops
}

/** Another mixdown; a bitrate outside the new layout's range becomes its default. */
export function mixdownChangeOps(
  index: number,
  track: AudioOutputTrack,
  mixdown: Mixdown | null,
  definitions: Definitions | null,
  channels: number,
): JsonPatchOp[] {
  const base = `/audio/${index}`
  const encoder = definitions?.audio_encoders?.[track.encoder ?? DEFAULT_AUDIO_ENCODER]
  const ops = [replace(`${base}/mixdown`, mixdown)]
  const bitrate = fittedBitrate(track.bitrate, encoder, bitrateTable(encoder, mixdown, channels))
  if (bitrate !== (track.bitrate ?? null)) ops.push(replace(`${base}/bitrate`, bitrate))
  return ops
}

/** Bitrate or VBR quality: the other one is cleared (the core takes the bitrate first). */
export function rateModeOps(
  index: number,
  mode: 'bitrate' | 'quality',
  encoder: AudioEncoderDef | undefined,
): JsonPatchOp[] {
  const base = `/audio/${index}`
  if (mode === 'quality') {
    return [
      replace(`${base}/bitrate`, null),
      replace(`${base}/quality`, encoder?.quality?.default ?? null),
    ]
  }
  return [replace(`${base}/quality`, null), replace(`${base}/bitrate`, null)]
}

/**
 * Another subtitle action: Convert gets the container's text format when it has none, and a
 * format or forced-only setting the new action does not use is cleared.
 */
export function subtitleActionOps(
  index: number,
  track: SubtitleOutputTrack,
  action: SubtitleOutputTrack['action'],
  container: ContainerDef | undefined,
): JsonPatchOp[] {
  const base = `/subtitles/${index}`
  const ops = [replace(`${base}/action`, action)]
  if (action === 'convert' && !track.convert_to) {
    ops.push(replace(`${base}/convert_to`, container?.text_subtitle_target ?? 'srt'))
  }
  if (action !== 'convert' && track.convert_to) ops.push(replace(`${base}/convert_to`, null))
  if (action !== 'burn' && track.forced_only) ops.push(replace(`${base}/forced_only`, false))
  return ops
}
