import type {
  AudioOutputTrack,
  AudioStream,
  Definitions,
  ExternalSubtitle,
  JsonPatchOp,
  Language,
  SubtitleFileInfo,
  SubtitleOutputTrack,
  SubtitleStream,
  TrackFlags,
  TrackMetadata,
} from '@/api/types'
import { findLanguage } from '@/components/base/languages'
import { channelsText } from '@/components/media/streams'

import { DEFAULT_AUDIO_ENCODER } from './ops'

export type MetadataList = 'video' | 'audio' | 'subtitles'
export type Flag = keyof TrackFlags

/** In the order the metadata block shows them. */
export const FLAGS: readonly Flag[] = [
  'default',
  'forced',
  'commentary',
  'hearing_impaired',
  'visual_impaired',
  'original',
]

const NO_FLAGS: TrackFlags = {
  default: false,
  forced: false,
  commentary: false,
  hearing_impaired: false,
  visual_impaired: false,
  original: false,
}

export const EMPTY_METADATA: TrackMetadata = { ...NO_FLAGS, language: null, name: null }

/** What a metadata edit sets; a member that is missing is left as it is. */
export type MetadataChanges = Partial<TrackMetadata>

/** The JSON pointer and the validation path of a track's metadata block. */
export function metadataPlace(
  list: MetadataList,
  index: number | undefined,
): { pointer: string; path: string } {
  if (list === 'video') return { pointer: '/video/metadata', path: 'video.metadata' }
  return { pointer: `/${list}/${index ?? 0}/metadata`, path: `${list}[${index ?? 0}].metadata` }
}

/** The validation paths of a metadata block's fields. */
export function metadataPaths(path: string): string[] {
  return [`${path}.language`, `${path}.name`, ...FLAGS.map((flag) => `${path}.${flag}`)]
}

export function externalOf(track: SubtitleOutputTrack | undefined): ExternalSubtitle | null {
  return track !== undefined && typeof track.source === 'object' ? track.source : null
}

/**
 * The patch for `changes` to one metadata block; a job without the block gets all of it. For an
 * external file, the same changes go to its source, so that both say the same.
 */
export function metadataOps(
  pointer: string,
  current: TrackMetadata | undefined,
  changes: MetadataChanges,
  external: ExternalSubtitle | null = null,
): JsonPatchOp[] {
  const ops: JsonPatchOp[] = []
  if (current === undefined) {
    ops.push({ op: 'add', path: pointer, value: { ...EMPTY_METADATA, ...changes } })
  } else {
    for (const [key, value] of Object.entries(changes)) {
      if (value === undefined || current[key as keyof TrackMetadata] === value) continue
      ops.push({ op: 'add', path: `${pointer}/${key}`, value })
    }
  }
  if (external !== null) ops.push(...externalMirrorOps(pointer, external, changes))
  return ops
}

function externalMirrorOps(
  metadataPointer: string,
  external: ExternalSubtitle,
  changes: MetadataChanges,
): JsonPatchOp[] {
  const base = metadataPointer.replace(/\/metadata$/, '/source')
  const ops: JsonPatchOp[] = []
  for (const key of ['language', 'name'] as const) {
    const value = changes[key]
    if (value !== undefined && (external[key] ?? null) !== value) {
      ops.push({ op: 'add', path: `${base}/${key}`, value })
    }
  }
  const flags = FLAGS.filter((flag) => changes[flag] !== undefined)
  if (flags.length === 0) return ops
  if (external.flags === undefined) {
    const value = { ...NO_FLAGS }
    for (const flag of flags) value[flag] = changes[flag] === true
    ops.push({ op: 'add', path: `${base}/flags`, value })
    return ops
  }
  for (const flag of flags) {
    if (external.flags[flag] !== changes[flag]) {
      ops.push({ op: 'add', path: `${base}/flags/${flag}`, value: changes[flag] })
    }
  }
  return ops
}

/** One patch (one undo step) for the same changes to several tracks of a list. */
export function bulkOps(
  list: 'audio' | 'subtitles',
  tracks: readonly (AudioOutputTrack | SubtitleOutputTrack)[],
  indexes: Iterable<number>,
  changes: MetadataChanges,
): JsonPatchOp[] {
  const ops: JsonPatchOp[] = []
  for (const index of [...new Set(indexes)].toSorted((a, b) => a - b)) {
    const track = tracks[index]
    if (track === undefined) continue
    const external = list === 'subtitles' ? externalOf(track as SubtitleOutputTrack) : null
    ops.push(...metadataOps(metadataPlace(list, index).pointer, track.metadata, changes, external))
  }
  return ops
}

/** The values of a track name template for one track, as the codec rules render them. */
export type NameValues = Partial<Record<NameVariable, string>>
export type NameVariable =
  | 'lang'
  | 'lang_name'
  | 'lang_native'
  | 'channels'
  | 'codec'
  | 'title'
  | 'source_codec'

/** The variables of a track name template, which the server fills in for the job. */
export const NAME_VARIABLES: readonly string[] = [
  'lang',
  'lang_name',
  'lang_native',
  'channels',
  'codec',
  'bitrate',
  'title',
  'source_codec',
]

/** The templates offered for a track name, as the codec rules write them. */
export const NAME_TEMPLATES: Record<'audio' | 'other', readonly NameVariable[][]> = {
  audio: [
    ['lang_name', 'channels', 'codec'],
    ['lang_native', 'channels', 'codec'],
    ['lang_name', 'channels'],
    ['lang_native', 'channels'],
    ['lang_name'],
    ['lang_native'],
    ['title'],
  ],
  other: [['lang_name'], ['lang_native'], ['lang_name', 'codec'], ['title']],
}

export interface NameSuggestion {
  /** `{lang_name} {channels} {codec}`. */
  template: string
  /** `Japanese 5.1 AC-3`. */
  text: string
}

/**
 * The offered names for a track: each template rendered with its values. A template with an
 * empty variable is left out (it would read `Japanese  AC-3`), and so is a text another
 * template already gave.
 */
export function nameSuggestions(
  templates: readonly NameVariable[][],
  values: NameValues,
): NameSuggestion[] {
  const seen = new Set<string>()
  const result: NameSuggestion[] = []
  for (const variables of templates) {
    const parts = variables.map((variable) => values[variable]?.trim() ?? '')
    if (parts.some((part) => part === '')) continue
    const text = parts.join(' ')
    if (seen.has(text)) continue
    seen.add(text)
    result.push({ template: variables.map((variable) => `{${variable}}`).join(' '), text })
  }
  return result
}

function capitalized(text: string): string {
  return text.charAt(0).toLocaleUpperCase() + text.slice(1)
}

/** `lang`, `lang_name` and `lang_native` of a language tag, as the core renders them. */
export function languageValues(languages: readonly Language[], tag: string | null): NameValues {
  if (!tag) return {}
  const language = findLanguage(languages, tag)
  if (language === undefined) return { lang: tag }
  return {
    lang: language.tag,
    lang_name: language.english_name,
    lang_native: capitalized(language.native_name),
  }
}

/** The output layout of an audio track: its mixdown's (`5.1`, `2.0`), else the source's. */
function outputChannels(
  track: AudioOutputTrack,
  stream: AudioStream | undefined,
  definitions: Definitions | null,
  copied: boolean,
): string | undefined {
  const mixdown = track.mixdown ? definitions?.mixdowns?.[track.mixdown] : undefined
  if (!copied && mixdown !== undefined) return `${mixdown.channels - mixdown.lfe}.${mixdown.lfe}`
  return (stream && channelsText(stream)) ?? undefined
}

function codecOf(stream: AudioStream | SubtitleStream | undefined): string | undefined {
  return stream?.display_codec || stream?.codec || undefined
}

/** The name template values of an output audio track. */
export function audioNameValues(
  track: AudioOutputTrack,
  stream: AudioStream | undefined,
  context: { languages: readonly Language[]; definitions: Definitions | null; copied: boolean },
): NameValues {
  const language = track.metadata?.language || streamTag(stream)
  const encoder = context.definitions?.audio_encoders?.[track.encoder ?? DEFAULT_AUDIO_ENCODER]
  return {
    ...languageValues(context.languages, language),
    channels: outputChannels(track, stream, context.definitions, context.copied),
    codec: context.copied ? codecOf(stream) : (encoder?.label ?? track.encoder ?? undefined),
    title: stream?.title ?? undefined,
    source_codec: codecOf(stream),
  }
}

/** The name template values of an output subtitle track (or the video track). */
export function otherNameValues(
  language: string | null | undefined,
  stream: AudioStream | SubtitleStream | undefined,
  context: { languages: readonly Language[]; codec?: string | null; title?: string | null },
): NameValues {
  const codec = context.codec ?? codecOf(stream)
  return {
    ...languageValues(context.languages, language || streamTag(stream)),
    codec: codec ?? undefined,
    title: (context.title ?? stream?.title) || undefined,
    source_codec: codec ?? undefined,
  }
}

function streamTag(stream: AudioStream | SubtitleStream | undefined): string | null {
  return stream?.language_ietf || stream?.language || null
}

/**
 * Encodings offered for a text subtitle file that is not UTF-8: the Windows code pages and ISO
 * 8859 sets most subtitle files were saved in, by iconv's names (`-sub_charenc` passes them on).
 */
export const CHARSETS: readonly string[] = [
  'CP1250',
  'CP1251',
  'CP1252',
  'CP1253',
  'CP1254',
  'CP1255',
  'CP1256',
  'CP1257',
  'CP1258',
  'ISO-8859-1',
  'ISO-8859-2',
  'ISO-8859-5',
  'ISO-8859-7',
  'ISO-8859-9',
  'ISO-8859-15',
  'KOI8-R',
  'KOI8-U',
  'CP437',
  'CP850',
  'CP852',
  'SHIFT_JIS',
  'EUC-JP',
  'GB18030',
  'BIG5',
  'EUC-KR',
  'TIS-620',
]

const FORCED_WORDS = new Set(['forced', 'foreign'])
// Not `hi`: that is Hindi.
const SDH_WORDS = new Set(['sdh', 'cc'])

/**
 * What the file name says about a subtitle file: its language, forced and hearing impaired. Only
 * the parts right before the extension count, so a word of the title is not taken for a language.
 */
export function fromFileName(
  path: string,
  languages: readonly Language[],
): { language: string | null; forced: boolean; hearing_impaired: boolean } {
  const name = path.split(/[/\\]/).at(-1) ?? ''
  const parts = name.split('.').slice(1, -1)
  const result = { language: null as string | null, forced: false, hearing_impaired: false }
  for (const part of parts.toReversed()) {
    const word = part.toLowerCase()
    if (FORCED_WORDS.has(word)) result.forced = true
    else if (SDH_WORDS.has(word)) result.hearing_impaired = true
    else {
      result.language = findLanguage(languages, part.replace('_', '-'))?.tag ?? null
      break
    }
  }
  return result
}

/** A new output track for an external file: copied, and never the default. */
export function externalTrack(
  info: Pick<SubtitleFileInfo, 'path'>,
  languages: readonly Language[],
): SubtitleOutputTrack {
  const guessed = fromFileName(info.path, languages)
  const flags: TrackFlags = {
    ...NO_FLAGS,
    forced: guessed.forced,
    hearing_impaired: guessed.hearing_impaired,
  }
  return {
    action: 'copy',
    convert_to: null,
    forced_only: false,
    source: {
      path: info.path,
      language: guessed.language,
      name: null,
      flags,
      offset_ms: 0,
      // None for UTF-8 (FFmpeg reads it with or without a byte order mark) and for UTF-16
      // (`-sub_charenc UTF-16LE` loses every event). An undetected encoding starts with none too.
      charset: null,
    },
    metadata: { ...flags, language: guessed.language, name: null },
  }
}
