import { describe, expect, it } from 'vitest'

import {
  completeAudio,
  completeSubtitles,
  fixesOnly,
  keyedPath,
  keysAfter,
  newRule,
  shownAtField,
} from './model'

describe('completing the defaults a preset holds', () => {
  it('fills what a hand-written preset leaves out with the model defaults', () => {
    const audio = completeAudio({ codec_rules: [{ codec: 'libopus' } as never] })
    expect(audio.selection).toMatchObject({ languages: null, no_match: 'default_flagged' })
    expect(audio.selection?.default_track).toBe('first_output')
    expect(audio.codec_rules?.[0]).toMatchObject({
      languages: null,
      source_channels: 'any',
      codec: 'libopus',
      if_fits: 'passthru',
      extras: { gain: 0, loudness: 'off', extra_outputs: [] },
    })
    expect(audio.passthru?.allowed).toHaveLength(9)
  })

  it('gives a preset without codec rules the one catch-all rule of a new preset', () => {
    expect(completeAudio(undefined).codec_rules).toEqual([
      expect.objectContaining({ source_channels: 'any', mixdown: 'up_to_5.1', max_bitrate: 256 }),
    ])
  })

  it("uses the subtitle selection's own defaults: no match takes none, no default track", () => {
    const subtitles = completeSubtitles({ selection: { languages: ['hu'] } as never } as never)
    expect(subtitles.selection).toMatchObject({
      languages: ['hu'],
      no_match: 'none',
      default_track: 'none',
      tracks_per_language: 'first',
    })
    expect(subtitles).toMatchObject({ foreign_audio_search: false, burn_in: 'none' })
  })

  it('keeps a member it does not know, so that saving writes it back', () => {
    const audio = completeAudio({ future: 1 } as never) as unknown as Record<string, unknown>
    expect(audio.future).toBe(1)
  })
})

describe('a new rule', () => {
  it('is not a catch-all and takes the catch-all encoder and max', () => {
    const rule = newRule({
      languages: null,
      source_channels: 'any',
      codec: 'libopus',
      mixdown: 'stereo',
      max_bitrate: 128,
      if_fits: 'reencode',
    })
    expect(rule.source_channels).not.toBe('any')
    expect(rule).toMatchObject({ codec: 'libopus', max_bitrate: 128, if_fits: 'passthru' })
  })
})

describe('issue paths and rule keys', () => {
  it('names a rule by its key, at any depth, and leaves other paths alone', () => {
    expect(keyedPath('audio_defaults.codec_rules[1].max_bitrate', [7, 9, 11])).toBe(
      'audio_defaults.codec_rules[k9].max_bitrate',
    )
    expect(keyedPath('audio_defaults.codec_rules[2]', [7, 9, 11])).toBe(
      'audio_defaults.codec_rules[k11]',
    )
    expect(keyedPath('audio_defaults.passthru.fallback_encoder', [7])).toBe(
      'audio_defaults.passthru.fallback_encoder',
    )
  })

  it('moves, removes and adds keys as a fix moves, removes and adds rules', () => {
    let next = 20
    const key = () => ++next
    expect(
      keysAfter(
        [1, 2, 3],
        [
          {
            op: 'move',
            from: '/audio_defaults/codec_rules/1',
            path: '/audio_defaults/codec_rules/0',
          },
        ],
        key,
      ),
    ).toEqual([2, 1, 3])
    expect(
      keysAfter([1, 2, 3], [{ op: 'remove', path: '/audio_defaults/codec_rules/1' }], key),
    ).toEqual([1, 3])
    expect(
      keysAfter([1, 2], [{ op: 'add', path: '/audio_defaults/codec_rules/1', value: {} }], key),
    ).toEqual([1, 21, 2])
    expect(
      keysAfter(
        [1, 2],
        [{ op: 'replace', path: '/audio_defaults/codec_rules/0/codec', value: 'ac3' }],
        key,
      ),
    ).toEqual([1, 2])
  })

  it('offers a fix only when every operation stays inside the edited defaults', () => {
    const inside = {
      op: 'replace',
      path: '/audio_defaults/codec_rules/0/codec',
      value: 'libopus',
    } as const
    const container = { op: 'replace', path: '/output/container', value: 'mkv' } as const
    expect(fixesOnly([inside], 'audio_defaults')).toBe(true)
    expect(fixesOnly([inside], 'subtitle_defaults')).toBe(false)
    expect(fixesOnly([inside, container], 'audio_defaults')).toBe(false)
    expect(
      fixesOnly([{ op: 'move', from: '/output/x', path: '/audio_defaults/y' }], 'audio_defaults'),
    ).toBe(false)
    expect(fixesOnly([], 'audio_defaults')).toBe(false)
  })

  it('knows which issues show beside a rule or a field, and which only in the preview', () => {
    expect(shownAtField('audio_defaults.codec_rules[k3]')).toBe(true)
    expect(shownAtField('audio_defaults.codec_rules[k3].extras.extra_outputs[0].codec')).toBe(true)
    expect(shownAtField('audio_defaults.selection.no_match')).toBe(true)
    expect(shownAtField('subtitle_defaults.burn_in')).toBe(true)
    expect(shownAtField('audio_defaults.passthru.fallback_encoder')).toBe(true)
    expect(shownAtField('audio_defaults.codec_rules[3]')).toBe(false)
    expect(shownAtField('audio_defaults')).toBe(false)
  })
})
