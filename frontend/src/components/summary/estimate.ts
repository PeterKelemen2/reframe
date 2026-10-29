import type {
  AudioOutputTrack,
  AudioStream,
  Definitions,
  JobSettings,
  MediaSource,
} from '@/api/types'

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
  const total = source.container?.duration ?? source.video?.[0]?.duration ?? null
  const range = job.range ?? { kind: 'full' }
  switch (range.kind) {
    case 'full':
      return total
    case 'time': {
      const end = range.end ?? total
      return end === null ? null : Math.max(0, end - range.start)
    }
    case 'chapters': {
      const chapters = source.chapters ?? []
      const first = chapters[range.start - 1]
      const last = chapters[range.end - 1]
      return first && last ? Math.max(0, last.end - first.start) : null
    }
    case 'frames': {
      const video = source.video?.[0]
      const rate = video?.avg_frame_rate ?? video?.frame_rate
      if (!rate || rate.num <= 0 || rate.den <= 0) return null
      const fps = rate.num / rate.den
      const end = range.end ?? video?.frame_count ?? (total === null ? null : total * fps)
      return end === null ? null : Math.max(0, (end - range.start) / fps)
    }
  }
  return null
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
