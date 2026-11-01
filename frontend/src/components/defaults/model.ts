import type {
  AudioCodecRule,
  AudioDefaults,
  JsonPatchOp,
  Schemas,
  SubtitleDefaults,
} from '@/api/types'
import { cloneJson } from '@/editor/patch'

export type TrackSelection = Schemas['TrackSelection']
export type AudioRuleExtras = Schemas['AudioRuleExtras']
export type ExtraAudioOutput = Schemas['ExtraAudioOutput']
export type PassthruCodec = NonNullable<Schemas['PassthruPolicy']['allowed']>[number]
export type RuleMixdown = AudioCodecRule['mixdown']

export const PASSTHRU_CODECS: readonly PassthruCodec[] = [
  'ac3',
  'eac3',
  'dts',
  'dtshd',
  'truehd',
  'aac',
  'mp3',
  'flac',
  'opus',
]

// The model's defaults: a preset written by hand may leave any of them out.
const AUDIO_SELECTION: TrackSelection = {
  languages: null,
  tracks_per_language: 'first',
  tie_break: 'best_quality',
  undetermined: 'other',
  other_languages: 'drop',
  no_match: 'default_flagged',
  commentary: 'drop',
  order: 'language_list',
  default_track: 'first_output',
}

const SUBTITLE_SELECTION: TrackSelection = {
  ...AUDIO_SELECTION,
  no_match: 'none',
  default_track: 'none',
}

function completeExtras(extras: Partial<AudioRuleExtras> | undefined): AudioRuleExtras {
  return {
    samplerate: null,
    gain: 0,
    drc: 0,
    loudness: 'off',
    name_template: null,
    first_track_of_language_only: false,
    ...extras,
    extra_outputs: extras?.extra_outputs ?? [],
  }
}

function completeRule(rule: Partial<AudioCodecRule>): AudioCodecRule {
  return {
    languages: null,
    source_channels: 'any',
    codec: 'aac',
    mixdown: 'keep',
    max_bitrate: null,
    if_fits: 'passthru',
    ...rule,
    extras: completeExtras(rule.extras),
  }
}

/** A deep copy of `defaults` with every member the model gives a default value. */
export function completeAudio(defaults: AudioDefaults | undefined): AudioDefaults {
  const rules: Partial<AudioCodecRule>[] = defaults?.codec_rules ?? [
    { mixdown: 'up_to_5.1', max_bitrate: 256 },
  ]
  return cloneJson({
    ...defaults,
    selection: { ...AUDIO_SELECTION, ...defaults?.selection },
    codec_rules: rules.map(completeRule),
    passthru: { allowed: [...PASSTHRU_CODECS], fallback_encoder: 'aac', ...defaults?.passthru },
  })
}

/** As `completeAudio`, with the subtitle selection's own defaults. */
export function completeSubtitles(defaults: SubtitleDefaults | undefined): SubtitleDefaults {
  return cloneJson({
    foreign_audio_search: false,
    burn_in: 'none',
    ...defaults,
    selection: { ...SUBTITLE_SELECTION, ...defaults?.selection },
  } satisfies SubtitleDefaults)
}

/** A rule to fill in, with the catch-all's encoder and max bitrate. */
export function newRule(catchAll: AudioCodecRule | undefined): AudioCodecRule {
  return completeRule({
    languages: null,
    source_channels: '5.1_or_more',
    codec: catchAll?.codec ?? 'aac',
    mixdown: 'keep',
    max_bitrate: catchAll?.max_bitrate ?? null,
    if_fits: 'passthru',
  })
}

const RULE_PATH = /^audio_defaults\.codec_rules\[(\d+)\]/

/**
 * An issue path with the rule's index replaced by its key (`audio_defaults.codec_rules[k7]`), so
 * that an issue stays at its rule when the rules are moved before the next answer.
 */
export function keyedPath(path: string, keys: readonly number[]): string {
  return path.replace(RULE_PATH, (whole, index: string) => {
    const key = keys[Number(index)]
    return key === undefined ? whole : `audio_defaults.codec_rules[k${key}]`
  })
}

export function rulePath(key: number): string {
  return `audio_defaults.codec_rules[k${key}]`
}

const SHOWN_AT_FIELD = [
  /^audio_defaults\.codec_rules\[k\d+\]/,
  /^(audio|subtitle)_defaults\.selection\.(languages|tracks_per_language|tie_break|undetermined|other_languages|no_match|commentary|order|default_track)$/,
  /^audio_defaults\.passthru\.(allowed|fallback_encoder)$/,
  /^subtitle_defaults\.(foreign_audio_search|burn_in)$/,
]

/** The dialog shows an issue at this keyed path beside its rule or field. */
export function shownAtField(at: string): boolean {
  return SHOWN_AT_FIELD.some((pattern) => pattern.test(at))
}

const RULE_POINTER = /^\/audio_defaults\/codec_rules\/(\d+|-)$/

function ruleIndex(pointer: string | undefined, length: number): number | null {
  const found = pointer === undefined ? null : RULE_POINTER.exec(pointer)
  if (found === null) return null
  return found[1] === '-' ? length : Number(found[1])
}

/** The rule keys after `ops`: a fix may move, remove or add whole rules. */
export function keysAfter(
  keys: readonly number[],
  ops: readonly JsonPatchOp[],
  nextKey: () => number,
): number[] {
  const result = [...keys]
  for (const op of ops) {
    const at = ruleIndex(op.path, result.length)
    if (at === null) continue
    if (op.op === 'remove') result.splice(at, 1)
    else if (op.op === 'add' || op.op === 'copy') result.splice(at, 0, nextKey())
    else if (op.op === 'move') {
      const from = ruleIndex(op.from, result.length)
      if (from === null) continue
      const [moved] = result.splice(from, 1)
      if (moved !== undefined) result.splice(at, 0, moved)
    }
  }
  return result
}

/** A fix the dialog can apply: every operation stays inside the defaults it edits. */
export function fixesOnly(ops: readonly JsonPatchOp[], member: string): boolean {
  const inside = (pointer: string | undefined) =>
    pointer === undefined || pointer.startsWith(`/${member}/`)
  return (
    ops.length > 0 &&
    ops.every((op) => inside(op.path) && inside('from' in op ? op.from : undefined))
  )
}
