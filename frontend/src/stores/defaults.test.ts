import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import {
  type Deferred,
  deferred,
  FakeServer,
  json,
  problem,
  type Recorded,
} from '@/api/testing/fakes'
import type {
  AudioCodecRule,
  AudioOutputTrack,
  DefaultsPreviewRequest,
  JobDraft,
  JobTemplate,
  Preset,
  SubtitleOutputTrack,
  TrackDraft,
  ValidationIssue,
} from '@/api/types'
import { preset, presetList, userPreset } from '@/components/presets/testing'
import { probedSource } from '@/components/tracks/testing'
import { sampleDraft, sampleJob } from '@/editor/testing/samples'

import { PREVIEW_DEBOUNCE, useDefaultsStore } from './defaults'
import { useEditorStore } from './editor'
import { useSourcesStore } from './sources'
import { useToastStore } from './toasts'

const BUILT_IN = 'h265-mkv-1080p'
const MINE = 'mine'
const PREVIEW = 'POST /api/presets/defaults/preview'
const EXPLAIN = 'POST /api/jobs/explain'

function rule(overrides: Partial<AudioCodecRule> = {}): AudioCodecRule {
  return {
    languages: null,
    source_channels: 'any',
    codec: 'aac',
    mixdown: 'stereo',
    max_bitrate: 160,
    if_fits: 'reencode',
    ...overrides,
  }
}

function encoded(stream: number, encoder: string, bitrate: number): AudioOutputTrack {
  return {
    action: 'encode',
    encoder,
    mixdown: '5.1',
    bitrate,
    gain: 0,
    drc: 0,
    loudness: 'off',
    source_stream: stream,
  }
}

function trackDraft(overrides: Partial<TrackDraft> = {}): TrackDraft {
  return {
    audio: [],
    subtitles: [],
    decisions: [],
    subtitle_decisions: [],
    issues: [],
    ...overrides,
  }
}

function issueAt(path: string, code = 'defaults.rule_shadowed'): ValidationIssue {
  return { severity: 'warning', code, path, message: `${code} at ${path}`, fixes: [] }
}

function previewBody(request: Recorded | undefined): DefaultsPreviewRequest {
  return request?.body as DefaultsPreviewRequest
}

const toasts = () => useToastStore().items.map(({ severity, summary }) => ({ severity, summary }))

/** Lets the fake answers and the zero-delay timers run. */
async function flush(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0)
}

class DefaultsServer extends FakeServer {
  /** Preview answers in the order the requests came; `null`: answer at once with `answer`. */
  pending: Deferred<Response>[] = []
  hold = false
  answer: TrackDraft = trackDraft()
  explained: TrackDraft = trackDraft({ audio: [encoded(1, 'ac3', 320)] })
  presets: Preset[] = [preset(BUILT_IN, 'H.265 MKV 1080p'), userPreset(MINE, 'Mine')]

  constructor() {
    super()
    this.on('POST /api/jobs/draft', (request) => {
      const { source_id, preset_id } = request.body as { source_id: string; preset_id: string }
      const job = sampleJob()
      job.source.path = `/media/${source_id}.mkv`
      job.preset_id = preset_id ?? BUILT_IN
      return sampleDraft(job) satisfies JobDraft
    })
      .on('POST /api/presets/diff', [])
      .on('GET /api/presets', () => presetList(this.presets))
      .on(PREVIEW, () => {
        if (!this.hold) return json([this.answer])
        const answer = deferred<Response>()
        this.pending.push(answer)
        return answer.promise
      })
      .on(EXPLAIN, () => this.explained)
      .on(`GET /api/presets/${MINE}`, () => this.presets.find((each) => each.id === MINE))
      .on(`PUT /api/presets/${MINE}`, (request) => request.body)
      .on('POST /api/presets', (request) => {
        const body = request.body as { template: JobTemplate; name: string; category: string }
        return json(
          {
            ...body.template,
            id: 'new',
            name: body.name,
            category: body.category,
            description: '',
            built_in: false,
          },
          201,
        )
      })
  }

  previews(): Recorded[] {
    return this.requests.filter((request) => `${request.method} ${request.path}` === PREVIEW)
  }
}

async function jobOpen(presetId: string = BUILT_IN): Promise<void> {
  const sources = useSourcesStore()
  sources.entries = [
    { id: 'movie', path: '/media/movie.mkv', source: probedSource('dts-hd-ma') },
    { id: 'other', path: '/media/other.mkv', source: probedSource('multitrack') },
  ]
  sources.activeId = 'movie'
  await useEditorStore().open('movie', presetId)
  await flush()
}

async function opened(which: 'audio' | 'subtitles' = 'audio', presetId = BUILT_IN) {
  await jobOpen(presetId)
  const defaults = useDefaultsStore()
  await defaults.open(which, { kind: 'job' })
  await flush()
  return defaults
}

/** The group template: an explicit audio rule from an edit, and AAC defaults. */
function groupTemplate(): JobTemplate {
  return {
    schema_version: 1,
    output: { container: 'mkv' } as JobTemplate['output'],
    audio_defaults: { codec_rules: [rule()] },
    audio_rules: [{ selector: { kind: 'audio', languages: ['jpn'] } }],
    subtitle_rules: [{ selector: { kind: 'subtitle', languages: ['eng'] } }],
  } as JobTemplate
}

describe('the defaults store', () => {
  let server: DefaultsServer

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    server = new DefaultsServer()
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('opening', () => {
    it('sends the preview at once for the job: its preset defaults, its container and its source', async () => {
      const defaults = await opened()
      expect(defaults.visible).toBe(true)
      expect(server.previews()).toHaveLength(1)
      const body = previewBody(server.previews()[0])
      expect(body.source_ids).toEqual(['movie'])
      expect(body.container).toBe('mkv')
      expect(body.audio_defaults.codec_rules).toEqual([
        expect.objectContaining({ codec: 'aac', mixdown: 'stereo', max_bitrate: 160 }),
      ])
      expect(body.audio_defaults.passthru?.allowed).toEqual([])
      expect(defaults.preview).toEqual(server.answer)
      expect(defaults.previewing).toBe(false)
    })

    it('opens a preset from the presets view on that preset, with the open source', async () => {
      await jobOpen()
      server.presets = [
        preset(BUILT_IN, 'H.265 MKV 1080p'),
        userPreset(MINE, 'Mine', {
          output: { container: 'mp4' } as Preset['output'],
          audio_defaults: { codec_rules: [rule({ codec: 'libopus', max_bitrate: 96 })] },
        }),
      ]
      const defaults = useDefaultsStore()
      await defaults.open('audio', { kind: 'preset', presetId: MINE })
      await flush()
      const body = previewBody(server.previews()[0])
      expect(body.container).toBe('mp4')
      expect(body.audio_defaults.codec_rules?.[0]).toMatchObject({
        codec: 'libopus',
        max_bitrate: 96,
      })
      expect(defaults.readOnly).toBe(false)
    })

    it('without an open source sends no preview: there is nothing to draft', async () => {
      const defaults = useDefaultsStore()
      await defaults.open('audio', { kind: 'preset', presetId: BUILT_IN })
      await flush()
      expect(defaults.visible).toBe(true)
      expect(defaults.sourceId).toBeNull()
      expect(server.previews()).toHaveLength(0)
      expect(defaults.previewing).toBe(false)
    })

    it('does not open for a job whose preset is not known', async () => {
      server.presets = []
      server.on(`GET /api/presets/${BUILT_IN}`, () => problem(404, 'preset.not_found', 'No preset'))
      await jobOpen()
      const defaults = useDefaultsStore()
      await defaults.open('audio', { kind: 'job' })
      expect(defaults.visible).toBe(false)
      expect(toasts()).toEqual([
        {
          severity: 'error',
          summary: "The job's preset is not known, so its defaults cannot be shown",
        },
      ])
    })
  })

  describe('the live preview', () => {
    it('is sent once, 250 ms after the last edit', async () => {
      const defaults = await opened()
      const sent = server.previews().length
      const audio = defaults.audio!
      defaults.setAudio({ ...audio, passthru: { allowed: ['ac3'], fallback_encoder: 'aac' } })
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE - 50)
      defaults.setAudio({
        ...audio,
        passthru: { allowed: ['ac3', 'eac3'], fallback_encoder: 'aac' },
      })
      expect(defaults.previewing).toBe(true)
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE - 1)
      expect(server.previews()).toHaveLength(sent)
      await vi.advanceTimersByTimeAsync(1)
      expect(server.previews()).toHaveLength(sent + 1)
      expect(previewBody(server.previews().at(-1)).audio_defaults.passthru?.allowed).toEqual([
        'ac3',
        'eac3',
      ])
      expect(defaults.previewing).toBe(false)
    })

    it('never shows an older answer that comes after a newer one', async () => {
      const defaults = await opened()
      server.hold = true
      const older = trackDraft({ issues: [issueAt('audio_defaults.codec_rules[0]', 'older')] })
      const newer = trackDraft({ issues: [issueAt('audio_defaults.codec_rules[0]', 'newer')] })
      defaults.setAudio({
        ...defaults.audio!,
        passthru: { allowed: ['ac3'], fallback_encoder: 'aac' },
      })
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
      defaults.setAudio({
        ...defaults.audio!,
        passthru: { allowed: ['dts'], fallback_encoder: 'aac' },
      })
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
      expect(server.pending).toHaveLength(2)
      server.pending[1]!.resolve(json([newer]))
      await flush()
      expect(defaults.preview).toEqual(newer)
      server.pending[0]!.resolve(json([older]))
      await flush()
      expect(defaults.preview).toEqual(newer)
    })

    it('does not show an answer that comes after a newer edit, before the newer answer', async () => {
      const defaults = await opened()
      const shown = defaults.preview
      server.hold = true
      defaults.setAudio({
        ...defaults.audio!,
        passthru: { allowed: ['ac3'], fallback_encoder: 'aac' },
      })
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
      defaults.setAudio({
        ...defaults.audio!,
        passthru: { allowed: ['dts'], fallback_encoder: 'aac' },
      })
      server.pending[0]!.resolve(json([trackDraft({ issues: [issueAt('x', 'stale')] })]))
      await flush()
      expect(defaults.preview).toBe(shown)
      expect(defaults.previewing).toBe(true)
    })

    it("shows the server's refusal instead of the table, until an answer comes", async () => {
      const defaults = await opened()
      server.on(PREVIEW, () =>
        problem(404, 'source.unknown', 'Unknown source', 'The source is not open'),
      )
      defaults.setAudio({ ...defaults.audio! })
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
      expect(defaults.previewFailure).toBe('The source is not open')
      expect(defaults.preview).toBeNull()
      expect(toasts()).toEqual([])
      server.on(PREVIEW, () => json([server.answer]))
      defaults.setAudio({ ...defaults.audio! })
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
      expect(defaults.previewFailure).toBeNull()
      expect(defaults.preview).toEqual(server.answer)
    })

    it('is sent again at once when the source is read again (a measured bitrate)', async () => {
      await opened()
      const sent = server.previews().length
      const sources = useSourcesStore()
      const measured = probedSource('dts-hd-ma')
      measured.audio![0]!.bitrate = { value: 2_140_063, source: 'measured' }
      sources.entries = sources.entries.with(0, { ...sources.entries[0]!, source: measured })
      await flush()
      expect(server.previews()).toHaveLength(sent + 1)
    })

    it('is not sent after the dialog is closed', async () => {
      const defaults = await opened()
      const sent = server.previews().length
      defaults.setAudio({ ...defaults.audio! })
      defaults.close()
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE * 2)
      expect(server.previews()).toHaveLength(sent)
      expect(defaults.previewing).toBe(false)
    })

    it("sends the template that Apply sends, with the preset's own track rules", async () => {
      const audioRules = [
        {
          selector: { kind: 'audio', languages: ['en'] },
          multiple: true,
          required: true,
          settings: { kind: 'audio', action: 'encode', encoder: 'aac', bitrate: 96 },
        },
      ] as JobTemplate['audio_rules']
      server.presets = [
        preset(BUILT_IN, 'H.265 MKV 1080p'),
        userPreset(MINE, 'Mine', { audio_rules: audioRules }),
      ]
      const defaults = await opened('audio', MINE)
      defaults.setRule(0, rule({ codec: 'ac3', max_bitrate: 320 }))
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
      await defaults.apply()
      const sent = previewBody(server.previews().at(-1)).template
      const applied = server.requests.find((each) => `${each.method} ${each.path}` === EXPLAIN)
      expect(sent).toEqual((applied!.body as { template: JobTemplate }).template)
      expect(sent?.audio_rules).toEqual(audioRules)
      expect(sent?.audio_defaults?.codec_rules?.[0]).toMatchObject({ codec: 'ac3' })
    })

    it("says when the template's own track rules of the dialog's kind replace the defaults", async () => {
      server.presets = [
        preset(BUILT_IN, 'H.265 MKV 1080p'),
        userPreset(MINE, 'Mine', {
          subtitle_rules: [
            {
              selector: { kind: 'subtitle' },
              multiple: false,
              required: false,
              settings: { kind: 'subtitle', action: 'copy' },
            },
          ] as JobTemplate['subtitle_rules'],
        }),
      ]
      const defaults = await opened('audio', MINE)
      expect(defaults.ruledByTemplate).toBe(false)
      await defaults.open('subtitles', { kind: 'job' })
      expect(defaults.ruledByTemplate).toBe(true)
      await defaults.open('subtitles', { kind: 'preset', presetId: BUILT_IN })
      expect(defaults.ruledByTemplate).toBe(false)
    })

    it('keeps an issue at its rule when the rules move before the next answer', async () => {
      server.answer = trackDraft({
        issues: [issueAt('audio_defaults.codec_rules[1].max_bitrate', 'defaults.bitrate_snapped')],
      })
      const defaults = await opened()
      defaults.addRule()
      defaults.addRule()
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
      const [first, second] = defaults.ruleKeys
      server.hold = true
      defaults.moveRule(1, 0)
      expect(defaults.ruleKeys).toEqual([second, first, defaults.ruleKeys[2]])
      expect(defaults.issuesAt(`audio_defaults.codec_rules[k${second}].max_bitrate`)).toHaveLength(
        1,
      )
      expect(defaults.issuesAt(`audio_defaults.codec_rules[k${first}].max_bitrate`)).toHaveLength(0)
    })
  })

  describe('the codec rules', () => {
    it('adds a rule above the catch-all, and never moves or removes the catch-all', async () => {
      const defaults = await opened()
      defaults.addRule()
      const rules = () => defaults.audio!.codec_rules!
      expect(rules()).toHaveLength(2)
      expect(rules()[1]).toMatchObject({ languages: null, source_channels: 'any', codec: 'aac' })
      expect(rules()[0]?.source_channels).toBe('5.1_or_more')
      const before = rules()
      defaults.removeRule(1)
      defaults.moveRule(1, 0)
      defaults.moveRule(0, 1)
      expect(rules()).toEqual(before)
      defaults.removeRule(0)
      expect(rules()).toEqual([before[1]])
    })

    it('moves a rule among the others', async () => {
      const defaults = await opened()
      defaults.addRule()
      defaults.addRule()
      defaults.setRule(0, rule({ languages: ['hu'], source_channels: '5.1_or_more' }))
      defaults.moveRule(0, 1)
      expect(defaults.audio!.codec_rules![1]?.languages).toEqual(['hu'])
      expect(defaults.audio!.codec_rules![2]?.source_channels).toBe('any')
    })
  })

  describe('fixes', () => {
    const move = {
      label: 'Move rule 2 above rule 1',
      target: 'template' as const,
      patch: [
        {
          op: 'move' as const,
          from: '/audio_defaults/codec_rules/1',
          path: '/audio_defaults/codec_rules/0',
        },
      ],
    }
    const container = {
      label: 'Switch to MP4',
      target: 'template' as const,
      patch: [{ op: 'replace' as const, path: '/output/container', value: 'mp4' }],
    }

    it('applies a fix of the defaults, and the rule keys move with it', async () => {
      const defaults = await opened()
      defaults.addRule()
      defaults.addRule()
      defaults.setRule(1, rule({ languages: ['hu'], source_channels: '5.1_or_more' }))
      await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
      const [first, second, last] = defaults.ruleKeys
      defaults.applyFix(move)
      expect(defaults.audio!.codec_rules![0]?.languages).toEqual(['hu'])
      expect(defaults.ruleKeys).toEqual([second, first, last])
      expect(defaults.previewing).toBe(true)
    })

    it('offers no fix of another part of the template, and none of a read-only preset', async () => {
      const defaults = await opened()
      expect(defaults.offersFix(move)).toBe(true)
      expect(defaults.offersFix(container)).toBe(false)
      await defaults.open('audio', { kind: 'preset', presetId: BUILT_IN })
      expect(defaults.offersFix(move)).toBe(false)
    })

    it("applies no fix while a newer preview is due: its paths are the old answer's", async () => {
      const defaults = await opened()
      defaults.addRule()
      defaults.addRule()
      const rules = defaults.audio!.codec_rules
      defaults.applyFix(move)
      expect(defaults.audio!.codec_rules).toBe(rules)
    })
  })

  describe('applying to the job', () => {
    it("replaces the job's audio tracks with what the edited defaults draft, in one undo step", async () => {
      const defaults = await opened()
      const editor = useEditorStore()
      const before = editor.job!.audio
      defaults.setRule(0, rule({ codec: 'ac3', max_bitrate: 320 }))
      await defaults.apply()
      const request = server.requests.find((each) => `${each.method} ${each.path}` === EXPLAIN)
      const body = request?.body as { source_id: string; template: JobTemplate }
      expect(body.source_id).toBe('movie')
      expect(body.template.audio_defaults?.codec_rules?.[0]).toMatchObject({
        codec: 'ac3',
        max_bitrate: 320,
      })
      expect(body.template.video?.encoder).toBe('libx265')
      expect(editor.job!.audio).toEqual(server.explained.audio)
      expect(editor.job!.subtitles).toEqual(sampleJob().subtitles)
      expect(defaults.visible).toBe(false)
      editor.undo()
      expect(editor.job!.audio).toEqual(before)
      expect(editor.canUndo).toBe(false)
    })

    it('replaces the subtitle tracks from the subtitle defaults', async () => {
      const subtitle: SubtitleOutputTrack = { action: 'burn', forced_only: true, source: 6 }
      server.explained = trackDraft({ audio: [encoded(1, 'ac3', 320)], subtitles: [subtitle] })
      const defaults = await opened('subtitles')
      await defaults.apply()
      const editor = useEditorStore()
      expect(editor.job!.subtitles).toEqual([subtitle])
      expect(editor.job!.audio).toEqual(sampleJob().audio)
    })

    it('keeps the job and the dialog when the server refuses', async () => {
      server.on(EXPLAIN, () => problem(422, 'jobs.invalid', 'Refused'))
      const defaults = await opened()
      const before = useEditorStore().job
      await defaults.apply()
      expect(useEditorStore().job).toBe(before)
      expect(defaults.visible).toBe(true)
      expect(defaults.busy).toBe(false)
    })

    it('drops the answer when another job was opened meanwhile', async () => {
      const answer = deferred<TrackDraft>()
      server.on(EXPLAIN, () => answer.promise)
      const defaults = await opened()
      const applying = defaults.apply()
      await flush()
      await useEditorStore().open('other', BUILT_IN)
      await flush()
      answer.resolve(server.explained)
      await applying
      expect(useEditorStore().job!.audio).toEqual(sampleJob().audio)
      expect(defaults.visible).toBe(false)
    })
  })

  describe('saving', () => {
    it("saves a user preset's edited defaults into it, and nothing else of it", async () => {
      await jobOpen()
      const defaults = useDefaultsStore()
      await defaults.open('subtitles', { kind: 'preset', presetId: MINE })
      await flush()
      expect(defaults.changed).toBe(false)
      defaults.setSubtitles({ ...defaults.subtitles!, burn_in: 'first' })
      expect(defaults.changed).toBe(true)
      await defaults.save()
      const put = server.requests.find((each) => each.method === 'PUT')
      const body = put?.body as Preset
      expect(body.subtitle_defaults?.burn_in).toBe('first')
      expect(body.audio_defaults).toEqual(server.presets[1]!.audio_defaults)
      expect(body.name).toBe('Mine')
      expect(defaults.visible).toBe(false)
    })

    it("saves into the preset as the server has it now: another window's changes to it stay", async () => {
      await jobOpen()
      const defaults = useDefaultsStore()
      await defaults.open('audio', { kind: 'preset', presetId: MINE })
      await flush()
      const stale = server.presets[1]!
      const elsewhere = userPreset(MINE, 'Mine', {
        description: 'Changed in another window',
        video: { ...stale.video, encoder: 'libx264' } as Preset['video'],
        subtitle_defaults: { burn_in: 'first', foreign_audio_search: true },
      })
      server.presets = [server.presets[0]!, elsewhere]
      defaults.addRule()
      await defaults.save()
      const body = server.requests.find((each) => each.method === 'PUT')?.body as Preset
      expect(body.description).toBe('Changed in another window')
      expect(body.video?.encoder).toBe('libx264')
      expect(body.subtitle_defaults).toEqual({ burn_in: 'first', foreign_audio_search: true })
      expect(body.audio_defaults?.codec_rules).toHaveLength(2)
    })

    it('a preset deleted elsewhere is not saved: a toast, and the list is read again', async () => {
      await jobOpen()
      const defaults = useDefaultsStore()
      await defaults.open('audio', { kind: 'preset', presetId: MINE })
      await flush()
      server.on(`GET /api/presets/${MINE}`, () =>
        problem(404, 'preset.not_found', 'Not found', `No preset ${MINE}`),
      )
      const lists = server.count('GET /api/presets')
      defaults.addRule()
      await defaults.save()
      await flush()
      expect(server.requests.filter((each) => each.method === 'PUT')).toHaveLength(0)
      expect(toasts()).toEqual([
        { severity: 'error', summary: 'The defaults could not be saved in “Mine”' },
      ])
      expect(server.count('GET /api/presets')).toBe(lists + 1)
      expect(defaults.visible).toBe(true)
    })

    it('shows a built-in preset read-only: edits are ignored and nothing is saved', async () => {
      const defaults = useDefaultsStore()
      await defaults.open('audio', { kind: 'preset', presetId: BUILT_IN })
      const audio = defaults.audio
      expect(defaults.readOnly).toBe(true)
      defaults.setAudio({ ...audio!, passthru: { allowed: ['ac3'], fallback_encoder: 'aac' } })
      defaults.addRule()
      await defaults.save()
      expect(defaults.audio).toBe(audio)
      expect(server.requests.filter((each) => each.method === 'PUT')).toHaveLength(0)
    })

    it("saves the job's user preset and stays open, so the defaults can still be applied", async () => {
      const defaults = await opened('audio', MINE)
      defaults.setAudio({
        ...defaults.audio!,
        passthru: { allowed: ['ac3'], fallback_encoder: 'aac' },
      })
      await defaults.save()
      const body = server.requests.find((each) => each.method === 'PUT')?.body as Preset
      expect(body.audio_defaults?.passthru?.allowed).toEqual(['ac3'])
      expect(defaults.visible).toBe(true)
      expect(defaults.changed).toBe(false)
      expect(toasts()).toEqual([
        { severity: 'success', summary: 'The defaults are saved in “Mine”' },
      ])
    })

    it("a refused save is a toast with the server's reason, and the edits stay", async () => {
      server.on(`PUT /api/presets/${MINE}`, () => problem(422, 'preset.invalid', 'Invalid preset'))
      const defaults = await opened('audio', MINE)
      defaults.setAudio({
        ...defaults.audio!,
        passthru: { allowed: ['ac3'], fallback_encoder: 'aac' },
      })
      await defaults.save()
      expect(defaults.changed).toBe(true)
      expect(toasts()).toEqual([
        { severity: 'error', summary: 'The defaults could not be saved in “Mine”' },
      ])
    })

    it("saves a built-in job preset's edited defaults as a new preset from the job's settings", async () => {
      const defaults = await opened()
      defaults.setAudio({
        ...defaults.audio!,
        passthru: { allowed: ['ac3'], fallback_encoder: 'aac' },
      })
      await defaults.saveAsNew({ name: 'Hungarian AC-3', category: 'Custom', description: '' })
      const body = server.requests.find(
        (each) => `${each.method} ${each.path}` === 'POST /api/presets',
      )?.body as { template: JobTemplate; name: string }
      expect(body.name).toBe('Hungarian AC-3')
      expect(body.template.audio_defaults?.passthru?.allowed).toEqual(['ac3'])
      expect(body.template.video?.encoder).toBe('libx265')
      expect(defaults.changed).toBe(false)
    })
  })

  /** E01 and E02 are open (E02 shown, in scope `file`); the panel lists E01 first. */
  async function groupOpened(which: 'audio' | 'subtitles' = 'audio') {
    const sources = useSourcesStore()
    sources.entries = [
      { id: 'e2', path: '/media/Show.S01E02.mkv', source: probedSource('multitrack') },
      { id: 'e1', path: '/media/Show.S01E01.mkv', source: probedSource('dts-hd-ma') },
    ]
    sources.grouping = {
      groups: [
        {
          id: 'g1',
          name: 'Show S01',
          level: 'standard',
          representative: '/media/Show.S01E01.mkv',
          fingerprint: { level: 'standard', tracks: [], digest: 'd' },
          members: [
            { path: '/media/Show.S01E01.mkv', match: 'exact', episode: 1 },
            { path: '/media/Show.S01E02.mkv', match: 'exact', episode: 2 },
          ],
        },
      ],
    }
    const editor = useEditorStore()
    editor.target = {
      kind: 'group',
      groupId: 'g1',
      sourceId: 'e2',
      job: sampleJob(),
      template: groupTemplate(),
      presetId: BUILT_IN,
      overrides: {},
      scope: 'file',
    }
    const patchTemplate = vi.spyOn(editor, 'patchTemplate').mockImplementation(() => undefined)
    server.on(PREVIEW, (request) =>
      json(
        (request.body as DefaultsPreviewRequest).source_ids.map((id) =>
          trackDraft({ issues: [issueAt('audio_defaults.codec_rules[0]', `rule.${id}`)] }),
        ),
      ),
    )
    const defaults = useDefaultsStore()
    await defaults.open(which, { kind: 'group', groupId: 'g1' })
    await flush()
    return { defaults, editor, patchTemplate }
  }

  describe('a batch group', () => {
    it("edits the template's defaults and previews every file of the group as Apply would", async () => {
      const { defaults } = await groupOpened()
      expect(defaults.visible).toBe(true)
      expect(defaults.audio?.codec_rules).toEqual([expect.objectContaining(rule())])
      const body = previewBody(server.previews()[0])
      expect(body.source_ids).toEqual(['e1', 'e2'])
      expect(body.template?.audio_rules).toEqual([])
      expect(body.template?.subtitle_rules).toEqual(groupTemplate().subtitle_rules)
      expect(defaults.previews.map(({ id, label }) => ({ id, label }))).toEqual([
        { id: 'e1', label: 'E01' },
        { id: 'e2', label: 'E02' },
      ])
      // The rules show the issues of the shown file's answer.
      expect(defaults.issues.map(({ issue }) => issue.code)).toEqual(['rule.e2'])
    })

    it('applies the edited defaults to the template and drops its rules of that kind, then closes', async () => {
      const { defaults, patchTemplate } = await groupOpened('subtitles')
      const edited = { ...defaults.subtitles!, forced_only: true }
      defaults.setSubtitles(edited)
      await defaults.apply()
      expect(patchTemplate).toHaveBeenCalledTimes(1)
      expect(patchTemplate.mock.calls[0]?.[0]).toEqual([
        { op: 'add', path: '/subtitle_defaults', value: edited },
        { op: 'add', path: '/subtitle_rules', value: [] },
      ])
      expect(defaults.visible).toBe(false)
      expect(server.requests.some((each) => each.path === '/api/jobs/explain')).toBe(false)
    })

    it('closes when the group is left', async () => {
      const { defaults } = await groupOpened()
      await useEditorStore().open('e1', BUILT_IN)
      await flush()
      expect(defaults.visible).toBe(false)
    })
  })

  it("closes the job's dialog when another job is opened under it", async () => {
    const defaults = await opened()
    await useEditorStore().open('other', BUILT_IN)
    await flush()
    expect(defaults.visible).toBe(false)
  })
})
