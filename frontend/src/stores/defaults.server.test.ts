import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { boot, shutdown } from '@/api/boot'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { http } from '@/api/testing/serverHelpers'
import type { AudioCodecRule, Preset, TrackDecision } from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'

import { useDefaultsStore } from './defaults'
import { useEditorStore } from './editor'
import { templateOfPreset, usePresetsStore } from './presets'
import { useSourcesStore } from './sources'

const PORT = 8781
const TOKEN = 'defaults-test-token'
const BUILT_IN = 'h265-mkv-1080p'

let server: DevServer

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: [
      '--token',
      TOKEN,
      '--fixtures',
      'dts-hd-ma,multitrack',
      ...(tools === null ? [] : ['--tools-dir', tools]),
    ],
  })
}, 180_000)

afterAll(async () => {
  await server.stop()
})

beforeEach(async () => {
  setActivePinia(createPinia())
  await boot({ backend: async () => ({ baseUrl: server.url }), token: TOKEN })
})

afterEach(() => {
  shutdown()
})

async function jobOf(name: string): Promise<void> {
  await useSourcesStore().open([`${server.media}/${name}`])
  await vi.waitFor(() => expect(useEditorStore().job?.source.path).toContain(name), {
    timeout: 10_000,
  })
}

async function previewed(): Promise<void> {
  await vi.waitFor(() => expect(useDefaultsStore().previewing).toBe(false), { timeout: 10_000 })
}

function rule(overrides: Partial<AudioCodecRule>): AudioCodecRule {
  return {
    languages: null,
    source_channels: '5.1_or_more',
    codec: 'ac3',
    mixdown: '5.1',
    max_bitrate: 320,
    if_fits: 'passthru',
    ...overrides,
  }
}

/** The two AC-3 rules of the M6 demo, above the built-in preset's AAC catch-all. */
async function demoRules(): Promise<void> {
  const defaults = useDefaultsStore()
  await defaults.open('audio', { kind: 'job' })
  await previewed()
  defaults.addRule()
  defaults.addRule()
  defaults.setRule(0, rule({ languages: ['hu'], max_bitrate: 320 }))
  defaults.setRule(1, rule({ languages: ['en'], max_bitrate: 384 }))
  const audio = defaults.audio!
  defaults.setAudio({ ...audio, passthru: { ...audio.passthru!, allowed: ['ac3'] } })
  await previewed()
}

function row(decision: TrackDecision | undefined) {
  const output = decision?.outputs?.[0]
  return [
    decision?.source_stream,
    decision?.rule,
    output?.action,
    output?.encoder,
    output?.mixdown ?? null,
    output?.bitrate ?? null,
  ]
}

describe('the defaults dialog against a real server', () => {
  it('previews the demo rules on dts-hd-ma: DTS-HD MA → AC-3 320, AC-3 224 passed through, stereo to the next rule', async () => {
    await jobOf('dts-hd-ma.mkv')
    await demoRules()
    const decisions = useDefaultsStore().preview?.decisions ?? []
    expect(decisions.map(row)).toEqual([
      [1, 1, 'encode', 'ac3', '5.1', 320],
      [2, 2, 'passthru', 'ac3', null, null],
      [3, 3, 'encode', 'aac', 'stereo', 160],
    ])
    expect(decisions.map((decision) => decision.reason)).toEqual([
      'Lossless source → encode at the max',
      'AC-3, 5.1, 224 ≤ 384: passthru',
      'Rule 2 needs 5.1 or more. Rule 3 matches. The rule says re-encode, 192 > 160 → encode at the max',
    ])
    // The DTS-HD MA track has no bitrate in the file: the preview offers Measure.
    expect(decisions.map((decision) => decision.measure)).toEqual([true, false, false])
    expect(useDefaultsStore().issues).toEqual([])
  })

  it('applies the defaults to the job: its audio tracks become the drafted ones, one undo step', async () => {
    await jobOf('dts-hd-ma.mkv')
    const editor = useEditorStore()
    const before = editor.job!.audio
    await demoRules()
    await useDefaultsStore().apply()
    expect(useDefaultsStore().visible).toBe(false)
    expect(
      editor.job!.audio!.map((track) => [
        track.source_stream,
        track.action,
        track.encoder,
        track.bitrate ?? null,
      ]),
    ).toEqual([
      [1, 'encode', 'ac3', 320],
      [2, 'passthru', 'ac3', null],
      [3, 'encode', 'aac', 160],
    ])
    editor.undo()
    expect(editor.job!.audio).toEqual(before)
  })

  it("places the server's issues at their rules, and applies its fix to the right rule", async () => {
    await jobOf('dts-hd-ma.mkv')
    const defaults = useDefaultsStore()
    await defaults.open('audio', { kind: 'job' })
    await previewed()
    defaults.addRule()
    defaults.addRule()
    defaults.setRule(0, rule({ max_bitrate: 300 }))
    defaults.setRule(1, rule({ languages: ['hu'] }))
    await previewed()
    const [first, second] = defaults.ruleKeys
    const snapped = defaults.issuesAt(`audio_defaults.codec_rules[k${first}].max_bitrate`)
    expect(snapped.map((issue) => issue.code)).toEqual(['defaults.bitrate_snapped'])
    expect(
      defaults.issuesAt(`audio_defaults.codec_rules[k${second}]`).map((issue) => issue.code),
    ).toEqual(['defaults.rule_shadowed'])
    const fix = snapped[0]!.fixes!.find((each) => defaults.offersFix(each))!
    defaults.applyFix(fix)
    expect(defaults.audio!.codec_rules![0]!.max_bitrate).toBe(256)
    await previewed()
    expect(defaults.issuesAt(`audio_defaults.codec_rules[k${first}].max_bitrate`)).toEqual([])
  })

  it("saves a user preset's subtitle defaults into it, and nothing else", async () => {
    const presets = usePresetsStore()
    await presets.load()
    const builtIn = presets.byId(BUILT_IN)!
    const mine = await http<Preset>(server, 'POST', '/api/presets', {
      template: templateOfPreset(builtIn),
      name: `Defaults ${Date.now()}`,
      category: 'Custom',
      description: '',
    })
    await presets.load()
    const defaults = useDefaultsStore()
    await defaults.open('subtitles', { kind: 'preset', presetId: mine.id })
    const subtitles = defaults.subtitles!
    defaults.setSubtitles({
      ...subtitles,
      burn_in: 'first',
      selection: { ...subtitles.selection!, languages: ['en'] },
    })
    await defaults.save()
    expect(defaults.visible).toBe(false)
    const saved = await http<Preset>(server, 'GET', `/api/presets/${mine.id}`)
    expect(saved.subtitle_defaults?.burn_in).toBe('first')
    expect(saved.subtitle_defaults?.selection?.languages).toEqual(['en'])
    expect(saved.audio_defaults).toEqual(mine.audio_defaults)
    expect(saved.video).toEqual(mine.video)
  })
})
