import type { CapabilitySnapshot, EncoderStatus, JsonPatchOp, Schemas } from '@/api/types'
import type { StatusTone } from '@/components/base/types'

export type VideoEncoderDef = Schemas['VideoEncoderDef']
export type VideoSettings = Schemas['VideoSettings']
export type QualityMode = Schemas['QualityMode']
export type BitrateMode = Schemas['BitrateMode']
export type QualityBand = Schemas['QualityBand']
export type ChoiceSetting = Schemas['ChoiceSetting']
export type EncoderFamily = VideoEncoderDef['family']
export type RateControl = NonNullable<VideoSettings['rate_control']>
export type ConstantQuality = Schemas['ConstantQuality']
export type AverageBitrate = Schemas['AverageBitrate']

/** The picker's group order. */
export const FAMILY_ORDER: readonly EncoderFamily[] = ['software', 'nvenc', 'qsv', 'amf', 'vaapi']

export interface EncoderGroup {
  family: EncoderFamily
  encoders: VideoEncoderDef[]
}

/** The encoders by family, in `FAMILY_ORDER`; each family keeps the definitions' order. */
export function groupEncoders(encoders: Record<string, VideoEncoderDef>): EncoderGroup[] {
  const all = Object.values(encoders)
  return FAMILY_ORDER.map((family) => ({
    family,
    encoders: all.filter((encoder) => encoder.family === family),
  })).filter((group) => group.encoders.length > 0)
}

/**
 * - `checking`: being detected, or the encoder list was not read yet.
 * - `rechecking`: a cached failure that detection is checking again; the job may keep it.
 * - `untested`: in the build, not tested (hardware test encodes are off).
 * - `failed`: the check itself failed.
 */
export type AvailabilityKind =
  | 'available'
  | 'checking'
  | 'rechecking'
  | 'untested'
  | 'unavailable'
  | 'failed'
  | 'unknown'

export interface EncoderAvailability {
  kind: AvailabilityKind
  tone: StatusTone
  /** An unavailable encoder is shown but cannot be chosen. */
  selectable: boolean
  /** The server's reason (for `rechecking`: the last result's). */
  reason: string | null
  /** Unavailable because this FFmpeg build needs newer system software: another build helps. */
  buildMismatch: boolean
}

/** What the picker shows for an encoder, with the same rules as the server's encoder issues. */
export function availabilityOf(
  status: EncoderStatus | undefined,
  snapshot: CapabilitySnapshot | null,
): EncoderAvailability {
  const reason = status?.reason ?? null
  const buildMismatch = false
  if (status === undefined) {
    const kind = snapshot === null || snapshot.detecting ? 'checking' : 'unknown'
    const tone = kind === 'checking' ? 'busy' : 'off'
    return { kind, tone, selectable: true, reason: null, buildMismatch }
  }
  switch (status.state) {
    case 'available':
      return { kind: 'available', tone: 'ok', selectable: true, reason: null, buildMismatch }
    case 'checking':
      return { kind: 'checking', tone: 'busy', selectable: true, reason: null, buildMismatch }
    case 'unknown':
      // `in_build` is null until `ffmpeg -encoders` was read: that is still a detection.
      if (status.in_build === null || status.in_build === undefined) {
        return { kind: 'checking', tone: 'busy', selectable: true, reason: null, buildMismatch }
      }
      return { kind: 'untested', tone: 'off', selectable: true, reason, buildMismatch }
    case 'unavailable':
    case 'error':
      if (snapshot?.from_cache === true && snapshot.detecting) {
        return { kind: 'rechecking', tone: 'busy', selectable: true, reason, buildMismatch }
      }
      return {
        kind: status.state === 'error' ? 'failed' : 'unavailable',
        tone: 'error',
        selectable: false,
        reason,
        buildMismatch: status.state === 'unavailable' && status.build_mismatch === true,
      }
  }
}

function interpolate(points: readonly (readonly [number, number])[], x: number): number {
  for (let index = 1; index < points.length; index += 1) {
    const [x0, y0] = points[index - 1] as readonly [number, number]
    const [x1, y1] = points[index] as readonly [number, number]
    if (x <= x1 || index === points.length - 1) {
      if (Math.abs(x1 - x0) < 1e-9) return y0
      return y0 + ((y1 - y0) * (x - x0)) / (x1 - x0)
    }
  }
  return points[0]?.[1] ?? x
}

/** Halves round up whatever the sign, as the server does (`round_half_up`). */
function roundHalfUp(value: number): number {
  return Math.floor(Number(value.toFixed(9)) + 0.5)
}

/** `value` clamped to the scale and rounded to its step. */
export function roundToStep(
  value: number,
  mode: Pick<QualityMode, 'min' | 'max' | 'step'>,
): number {
  const clamped = Math.min(Math.max(value, mode.min), mode.max)
  const result = mode.min + roundHalfUp((clamped - mode.min) / mode.step) * mode.step
  return Number(Math.min(Math.max(result, mode.min), mode.max).toFixed(6))
}

/** A quality value on another encoder's scale, through the x264 RF scale (approximate). */
export function convertQuality(value: number, from: QualityMode, to: QualityMode): number {
  const clamped = Math.min(Math.max(value, from.min), from.max)
  const common = interpolate(from.scale, clamped)
  const inverse = to.scale.map(([x, y]) => [y, x] as const)
  return roundToStep(interpolate(inverse, common), to)
}

/** The recommended band for a picture whose short side has `lines` lines; `null` without one. */
export function bandFor(mode: QualityMode, lines: number | null): QualityBand | null {
  const bands = mode.recommended ?? []
  if (lines === null || bands.length === 0) return null
  return bands.find((band) => lines <= band.max_height) ?? bands.at(-1) ?? null
}

/** The choice setting of a video field (`preset` → `presets`). */
export const CHOICE_FIELDS = {
  preset: 'presets',
  tune: 'tunes',
  profile: 'profiles',
  level: 'levels',
} as const satisfies Record<string, keyof VideoEncoderDef>
export type ChoiceField = keyof typeof CHOICE_FIELDS

export function choiceSetting(encoder: VideoEncoderDef, field: ChoiceField): ChoiceSetting | null {
  return encoder[CHOICE_FIELDS[field]] ?? null
}

function hasChoice(setting: ChoiceSetting | null | undefined, value: string): boolean {
  return setting?.choices.some((choice) => choice.value === value) ?? false
}

/** `replace`, or `add` for a member the job does not have yet (an older job, a missing default). */
function put(video: VideoSettings, field: string, value: unknown): JsonPatchOp {
  const member = field.split('/')[0] ?? field
  const op = member in video ? 'replace' : 'add'
  return { op, path: `/video/${field}`, value } as JsonPatchOp
}

export const DEFAULT_BITRATE_KBPS = 6000

export function defaultBitrate(mode: BitrateMode): AverageBitrate {
  return {
    mode: 'bitrate',
    kbps: Math.min(Math.max(DEFAULT_BITRATE_KBPS, mode.min_kbps), mode.max_kbps),
    two_pass: false,
    turbo_first_pass: false,
  }
}

/** Why `encoder` cannot encode 10-bit here; `null` when it can or may (not tested yet). */
export function no10BitReason(
  encoder: VideoEncoderDef,
  status: EncoderStatus | undefined,
  snapshot: CapabilitySnapshot | null,
): 'no_mode' | 'test_failed' | null {
  if (!('10' in (encoder.pix_fmts ?? {}))) return 'no_mode'
  const rechecking = snapshot?.from_cache === true && snapshot.detecting
  if (status?.supports_10bit === false && !rechecking) return 'test_failed'
  return null
}

/** The bit depth, and a profile reset when the profile does not allow that depth. */
export function bitDepthOps(
  video: VideoSettings,
  encoder: VideoEncoderDef,
  depth: 8 | 10,
): JsonPatchOp[] {
  const ops = [put(video, 'bit_depth', depth)]
  const choice = encoder.profiles?.choices.find((candidate) => candidate.value === video.profile)
  const depths = choice?.bit_depths
  if (depths !== null && depths !== undefined && !depths.includes(depth)) {
    ops.push(put(video, 'profile', null))
  }
  return ops
}

/**
 * The patch that switches the video to `newId`: every value the new encoder does not have is
 * converted, moved into its range or reset, as the server's closest-match fix does. Custom
 * parameters are written for one encoder, so they are cleared too.
 */
export function switchEncoderOps(
  video: VideoSettings,
  newId: string,
  encoders: Record<string, VideoEncoderDef>,
  snapshot: CapabilitySnapshot | null,
): JsonPatchOp[] {
  const next = encoders[newId]
  if (next === undefined) throw new Error(`switchEncoderOps: unknown encoder ${newId}`)
  const old = encoders[video.encoder]
  const ops: JsonPatchOp[] = [put(video, 'encoder', newId)]
  const rc = video.rate_control
  const newQuality = next.rate_control?.quality ?? null
  const newBitrate = next.rate_control?.bitrate ?? null
  if (rc === undefined || rc.mode === 'quality') {
    const value = rc?.value ?? newQuality?.default ?? 0
    const oldQuality = old?.rate_control?.quality ?? null
    if (newQuality === null) {
      if (newBitrate !== null) ops.push(put(video, 'rate_control', defaultBitrate(newBitrate)))
    } else if (rc === undefined) {
      ops.push(put(video, 'rate_control', { mode: 'quality', value: newQuality.default }))
    } else {
      const converted =
        oldQuality === null
          ? roundToStep(value, newQuality)
          : convertQuality(value, oldQuality, newQuality)
      if (converted !== value) ops.push(put(video, 'rate_control/value', converted))
    }
  } else if (newBitrate === null) {
    if (newQuality !== null) {
      ops.push(put(video, 'rate_control', { mode: 'quality', value: newQuality.default }))
    }
  } else {
    const kbps = Math.min(Math.max(rc.kbps, newBitrate.min_kbps), newBitrate.max_kbps)
    if (kbps !== rc.kbps) ops.push(put(video, 'rate_control/kbps', kbps))
    if (rc.two_pass && (newBitrate.two_pass ?? null) === null) {
      ops.push(put(video, 'rate_control/two_pass', false))
      ops.push(put(video, 'rate_control/turbo_first_pass', false))
    }
  }
  for (const field of Object.keys(CHOICE_FIELDS) as ChoiceField[]) {
    const value = video[field]
    if (value !== null && value !== undefined && !hasChoice(choiceSetting(next, field), value)) {
      ops.push(put(video, field, null))
    }
  }
  if (
    video.bit_depth === 10 &&
    no10BitReason(next, snapshot?.encoders?.[newId], snapshot) !== null
  ) {
    ops.push(put(video, 'bit_depth', 8))
    const choice = next.profiles?.choices.find((candidate) => candidate.value === video.profile)
    const depths = choice?.bit_depths
    const reset = ops.some((op) => op.path === '/video/profile')
    if (depths !== null && depths !== undefined && !depths.includes(8) && !reset) {
      ops.push(put(video, 'profile', null))
    }
  }
  if (video.fast_decode && (next.fast_decode ?? null) === null) {
    ops.push(put(video, 'fast_decode', false))
  }
  const advanced = video.advanced ?? {}
  const kept = Object.fromEntries(
    Object.entries(advanced).filter(([key, value]) => fitsOption(next, key, value)),
  )
  if (Object.keys(kept).length !== Object.keys(advanced).length) {
    ops.push(put(video, 'advanced', kept))
  }
  if (video.custom_params && newId !== video.encoder) {
    ops.push(put(video, 'custom_params', ''))
  }
  return ops
}

/** The new encoder has the option and the value has its type and range. */
function fitsOption(
  encoder: VideoEncoderDef,
  key: string,
  value: boolean | number | string,
): boolean {
  const option = encoder.options?.find((candidate) => candidate.key === key)
  if (option === undefined) return false
  switch (option.type) {
    case 'bool':
      return typeof value === 'boolean'
    case 'int':
    case 'float':
      if (typeof value !== 'number') return false
      if (option.type === 'int' && !Number.isInteger(value)) return false
      return (option.min ?? -Infinity) <= value && value <= (option.max ?? Infinity)
    case 'enum':
      return (
        typeof value === 'string' &&
        (option.choices?.some((choice) => choice.value === value) ?? true)
      )
    default:
      return typeof value === 'string'
  }
}
