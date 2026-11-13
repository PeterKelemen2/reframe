import type {
  AudioOutputTrack,
  AudioStream,
  Definitions,
  JobSettings,
  MediaSource,
} from '@/api/types'
import { rangeSeconds } from '@/components/range/range'

export type Estimate =
  /** Constant quality: the size depends on the picture. */
  | { kind: 'quality' }
  /** The duration, or the bitrate of a copied video, is not known. */
  | { kind: 'unknown'; reason: 'duration' | 'video' }
  | {
      kind: 'size'
      bytes: number
      seconds: number
      videoKbps: number
      audioKbps: number
      /** Audio tracks left out of `bytes`: their bitrate is not known before the encode. */
      unknownTracks: number
    }

/** Seconds of the source that the job's range covers; `null` when the source does not say. */
export function jobDuration(job: JobSettings, source: MediaSource): number | null {
  return rangeSeconds(job, source)
}

const MIXDOWN_OF_CHANNELS: Record<number, string> = { 1: 'mono', 2: 'stereo', 6: '5.1', 8: '7.1' }

/** kb/s of one output audio track, or `null` when only the encode will tell. */
function audioKbps(
  track: AudioOutputTrack,
  stream: AudioStream | undefined,
  definitions: Definitions | null,
): number | null {
  // A copied track keeps the source's bitrate.
  if (track.action === 'passthru') {
    const value = stream?.bitrate?.value
    return value == null ? null : value / 1000
  }
  if (track.bitrate != null) return track.bitrate
  if (track.quality != null || track.encoder === null) return null
  const bitrate = definitions?.audio_encoders?.[track.encoder]?.bitrate
  const mixdown = track.mixdown ?? MIXDOWN_OF_CHANNELS[stream?.channels ?? 0]
  if (!bitrate || mixdown === undefined) return null
  return bitrate.by_mixdown?.[mixdown]?.default ?? null
}

/**
 * The output size from the bitrates: video and audio bitrates times the duration. Subtitles,
 * chapters and the container's overhead are left out; a copied stream counts at the source's
 * bitrate.
 */
export function estimateSize(
  job: JobSettings,
  source: MediaSource,
  definitions: Definitions | null,
): Estimate {
  const video = job.video
  let videoKbps = 0
  if (video?.passthrough) {
    const value = source.video?.[0]?.bitrate?.value
    if (value == null) return { kind: 'unknown', reason: 'video' }
    videoKbps = value / 1000
  } else if (video?.rate_control?.mode === 'bitrate') {
    videoKbps = video.rate_control.kbps
  } else if (video !== undefined) {
    return { kind: 'quality' }
  }
  const seconds = jobDuration(job, source)
  if (seconds === null) return { kind: 'unknown', reason: 'duration' }

  let total = 0
  let unknownTracks = 0
  for (const track of job.audio ?? []) {
    const stream = source.audio?.find((candidate) => candidate.index === track.source_stream)
    const kbps = audioKbps(track, stream, definitions)
    if (kbps === null) unknownTracks += 1
    else total += kbps
  }
  return {
    kind: 'size',
    bytes: ((videoKbps + total) * 1000 * seconds) / 8,
    seconds,
    videoKbps,
    audioKbps: total,
    unknownTracks,
  }
}
