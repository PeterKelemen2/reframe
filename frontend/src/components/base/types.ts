/** What `Field` gives its control: wire `id`, `aria-invalid` and `aria-describedby` with them. */
export interface FieldSlotProps {
  id: string
  /** The label's id, for a control that is a group (`aria-labelledby`): SelectButton, radios. */
  labelId: string
  invalid: boolean
  describedBy: string | undefined
}

/** The codec fields every stream model has (video, audio, subtitles). */
export interface CodecInfo {
  /** The commercial name (`DTS-HD MA`, `TrueHD Atmos`); shown. */
  display_codec?: string | null
  /** FFmpeg's codec name (`dts`); in the tooltip. */
  codec?: string | null
  codec_long?: string | null
  profile?: string | null
}

/** `StatusDot` colours: `ok` available, `busy` checking, `warn`, `error`, `off` unknown. */
export type StatusTone = 'ok' | 'busy' | 'warn' | 'error' | 'off'

/** Which kind of track a badge belongs to, where the names differ. */
export type TrackKind = 'audio' | 'subtitle'
