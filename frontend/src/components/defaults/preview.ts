import type {
  AudioOutputTrack,
  AudioStream,
  Definitions,
  SubtitleOutputTrack,
  TrackDecision,
} from '@/api/types'

type Translate = (key: string, named?: Record<string, unknown>) => string
/** `useI18n().n`: a number in the app's locale. */
type FormatNumber = (value: number) => string

/** The text of an audio output: encoder, mixdown and bitrate, or the passthru source codec. */
export function audioOutputText(
  output: AudioOutputTrack,
  stream: AudioStream | undefined,
  definitions: Definitions | null,
  t: Translate,
  n: FormatNumber,
): string {
  const encoder = output.encoder ?? ''
  if (output.action === 'passthru') {
    const codec = stream?.display_codec || stream?.codec || encoder
    return t('defaults.preview.passthruOf', { codec })
  }
  const name = definitions?.audio_encoders?.[encoder]?.label ?? encoder
  const layout = output.mixdown
    ? (definitions?.mixdowns?.[output.mixdown]?.label ?? output.mixdown)
    : ''
  const format = [name, layout].filter((part) => part !== '').join(' ')
  return output.bitrate
    ? t('defaults.preview.withBitrate', { format, kbps: n(output.bitrate) })
    : format
}

/** The text of a subtitle output: copy, convert or burn in. */
export function subtitleOutputText(output: SubtitleOutputTrack, t: Translate): string {
  if (output.action === 'burn') {
    return output.forced_only ? t('defaults.preview.burnForced') : t('defaults.preview.burn')
  }
  if (output.action === 'convert' && output.convert_to) {
    return t('defaults.preview.convert', { format: output.convert_to.toUpperCase() })
  }
  return t('defaults.preview.copy')
}

/** One line per output of a decision; empty for a dropped track. */
export function outputLines(
  decision: TrackDecision,
  stream: AudioStream | undefined,
  definitions: Definitions | null,
  t: Translate,
  n: FormatNumber,
): string[] {
  if (decision.kind === 'subtitle') {
    return (decision.subtitle_outputs ?? []).map((output) => subtitleOutputText(output, t))
  }
  return (decision.outputs ?? []).map((output) =>
    audioOutputText(output, stream, definitions, t, n),
  )
}
