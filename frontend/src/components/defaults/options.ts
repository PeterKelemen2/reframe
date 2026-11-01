import { useI18n } from 'vue-i18n'

import type { AudioCodecRule, SubtitleDefaults } from '@/api/types'

import type { AudioRuleExtras, TrackSelection } from './model'

export interface Option<T extends string> {
  value: T
  label: string
}

type Choices<T extends string> = readonly (readonly [T, string])[]

// Message keys by value: values such as `5.1_or_more` cannot be message keys (a dot nests).
const TRACKS_PER_LANGUAGE: Choices<TrackSelection['tracks_per_language']> = [
  ['none', 'none'],
  ['first', 'first'],
  ['all', 'all'],
]
const TIE_BREAK: Choices<TrackSelection['tie_break']> = [
  ['source_order', 'sourceOrder'],
  ['most_channels', 'mostChannels'],
  ['best_quality', 'bestQuality'],
]
const UNDETERMINED: Choices<TrackSelection['undetermined']> = [
  ['first_language', 'firstLanguage'],
  ['other', 'other'],
]
const OTHER_LANGUAGES: Choices<TrackSelection['other_languages']> = [
  ['drop', 'drop'],
  ['keep_first', 'keepFirst'],
  ['keep_all', 'keepAll'],
]
const NO_MATCH: Choices<TrackSelection['no_match']> = [
  ['default_flagged', 'defaultFlagged'],
  ['first_track', 'firstTrack'],
  ['none', 'none'],
]
const COMMENTARY: Choices<TrackSelection['commentary']> = [
  ['drop', 'drop'],
  ['keep_after_main', 'keepAfterMain'],
]
const ORDER: Choices<TrackSelection['order']> = [
  ['language_list', 'languageList'],
  ['source', 'source'],
]
// `forced` is meant for subtitles; audio offers it only when a preset already has it.
const AUDIO_DEFAULT_TRACK: Choices<TrackSelection['default_track']> = [
  ['first_output', 'firstOutput'],
  ['first_in_first_language', 'firstInFirstLanguage'],
  ['none', 'none'],
]
const SUBTITLE_DEFAULT_TRACK: Choices<TrackSelection['default_track']> = [
  ['none', 'none'],
  ['first_output', 'firstOutput'],
  ['forced', 'forced'],
  ['first_in_first_language', 'firstInFirstLanguage'],
]
const SOURCE_CHANNELS: Choices<AudioCodecRule['source_channels']> = [
  ['any', 'any'],
  ['mono', 'mono'],
  ['stereo_or_less', 'stereoOrLess'],
  ['5.1_or_more', 'surround51'],
  ['7.1_or_more', 'surround71'],
]
const MIXDOWN: Choices<AudioCodecRule['mixdown']> = [
  ['keep', 'keep'],
  ['up_to_5.1', 'upTo51'],
  ['5.1', 'surround51'],
  ['stereo', 'stereo'],
  ['dpl2', 'dpl2'],
  ['mono', 'mono'],
]
const IF_FITS: Choices<AudioCodecRule['if_fits']> = [
  ['passthru', 'passthru'],
  ['reencode', 'reencode'],
]
const LOUDNESS: Choices<AudioRuleExtras['loudness']> = [
  ['off', 'off'],
  ['ebu_r128', 'ebuR128'],
  ['streaming', 'streaming'],
]
const BURN_IN: Choices<SubtitleDefaults['burn_in']> = [
  ['none', 'none'],
  ['foreign_audio', 'foreignAudio'],
  ['first', 'first'],
  ['foreign_audio_then_first', 'foreignAudioThenFirst'],
]

/** The labelled choices of the defaults' selects. */
export function useDefaultsOptions() {
  const { t, locale } = useI18n()

  function options<T extends string>(group: string, choices: Choices<T>): Option<T>[] {
    return choices.map(([value, key]) => ({ value, label: t(`defaults.${group}.${key}`) }))
  }

  function defaultTrack(kind: 'audio' | 'subtitles', current: TrackSelection['default_track']) {
    let choices = kind === 'subtitles' ? SUBTITLE_DEFAULT_TRACK : AUDIO_DEFAULT_TRACK
    if (current === 'forced' && kind === 'audio') choices = [...choices, ['forced', 'forced']]
    return options('selection.defaultTrackChoice', choices)
  }

  /** Items as one list in the UI's language: `Hungarian, English`. */
  function list(items: readonly string[]): string {
    return new Intl.ListFormat(locale.value, { style: 'short', type: 'unit' }).format(items)
  }

  return {
    tracksPerLanguage: options('selection.tracksPerLanguageChoice', TRACKS_PER_LANGUAGE),
    tieBreak: options('selection.tieBreakChoice', TIE_BREAK),
    undetermined: options('selection.undeterminedChoice', UNDETERMINED),
    otherLanguages: options('selection.otherLanguagesChoice', OTHER_LANGUAGES),
    noMatch: options('selection.noMatchChoice', NO_MATCH),
    commentary: options('selection.commentaryChoice', COMMENTARY),
    order: options('selection.orderChoice', ORDER),
    defaultTrack,
    list,
    sourceChannels: options('rules.channelsChoice', SOURCE_CHANNELS),
    mixdown: options('rules.mixdownChoice', MIXDOWN),
    ifFits: options('rules.ifFitsChoice', IF_FITS),
    loudness: options('rules.loudnessChoice', LOUDNESS),
    burnIn: options('subtitles.burnInChoice', BURN_IN),
  }
}

/** The label of `value` among `options`, else the value itself. */
export function labelOf<T extends string>(options: readonly Option<T>[], value: T): string {
  return options.find((option) => option.value === value)?.label ?? value
}
