import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { boot, shutdown } from '@/api/boot'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { http } from '@/api/testing/serverHelpers'
import type { BatchResolution, JobTemplate, JsonPatchOp, Preset, Resolution } from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'

import { useEditorStore } from './editor'
import { templateOfPreset } from './presets'
import { useSourcesStore } from './sources'

const PORT = 8712
const TOKEN = 'group-test-token'
const SEASON = 'Anime.Show.S01.BluRay.x264-GRP'
const SOON = { timeout: 15_000, interval: 50 }

let server: DevServer

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: [
      '--token',
      TOKEN,
      '--fixtures',
      SEASON,
      ...(tools === null ? [] : ['--tools-dir', tools]),
    ],
  })
}, 120_000)

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

/** `E05` → the source id of episode 5. */
function episode(number: number): string {
  const code = `S01E${String(number).padStart(2, '0')}`
  const entry = useSourcesStore().entries.find((found) => found.path.includes(code))
  if (entry === undefined) throw new Error(`no ${code}`)
  return entry.id
}

function rowOf(resolution: BatchResolution, number: number): Resolution {
  const path = useSourcesStore().entries.find((entry) => entry.id === episode(number))?.path
  const found = resolution.rows?.find((candidate) => candidate.path === path)
  if (found === undefined) throw new Error(`no row for E${number}`)
  return found
}

/** Each row as `E01 ok`, with the cells that are not exact (`A2 missing`). */
function marks(resolution: BatchResolution): string[] {
  return (resolution.rows ?? []).map((found) => {
    const number = /S01E(\d\d)/.exec(found.path)?.[1] ?? '??'
    const cells = (found.matches ?? [])
      .filter((match) => match.status !== 'exact')
      .map((match) => `${match.kind === 'audio' ? 'A' : 'S'}${match.rule + 1} ${match.status}`)
    return [`E${number} ${found.status}`, ...cells].join(' ')
  })
}

function documentOf() {
  const current = useEditorStore().target
  if (current?.kind !== 'group') throw new Error('no group is edited')
  return structuredClone({ template: current.template, overrides: current.overrides })
}

/** Every row but `number`'s, as JSON: what a change of one file must leave alone. */
function others(resolution: BatchResolution, number: number): string {
  const own = rowOf(resolution, number)
  return JSON.stringify((resolution.rows ?? []).filter((found) => found !== own))
}

describe('a group in the editor against a real server', () => {
  it('edits the anime season as 04 says, with undo, overrides, picks and presets', async () => {
    const sources = useSourcesStore()
    const editor = useEditorStore()
    await sources.open([`${server.media}/${SEASON}`])
    const [season] = sources.grouping?.groups ?? []
    if (season === undefined) throw new Error('no group')
    expect(season.members).toHaveLength(12)

    // Edit group: the template of the editor's preset, the matrix of 12 rows.
    const { presets } = await http<{ presets: Preset[] }>(server, 'GET', '/api/presets')
    const preset = presets.find((candidate) => candidate.id === editor.presetId) as Preset
    await editor.editGroup(season.id)
    expect(documentOf()).toEqual({ template: templateOfPreset(preset), overrides: {} })
    expect(editor.target?.sourceId).toBe(episode(1))
    let resolution = await editor.resolveNow()
    expect(marks(resolution)).toEqual([
      'E01 ok',
      'E02 ok',
      'E03 ok',
      'E04 ok',
      'E05 warning',
      'E06 ok',
      'E07 ok',
      'E08 ok',
      'E09 ok',
      'E10 ok',
      // The fixture's E11 has no dub: a near member too.
      'E11 warning',
      'E12 ok',
    ])
    expect(rowOf(resolution, 5).issues?.map((found) => found.code)).toContain('batch.near_match')
    const steps = [documentOf()]

    // E01's audio and subtitles through editor.patch: explicit rules and 04's matrix.
    editor.patch([
      { op: 'replace', path: '/audio/0/encoder', value: 'libopus' },
      { op: 'replace', path: '/audio/0/mixdown', value: '5.1' },
      { op: 'replace', path: '/audio/0/bitrate', value: 448 },
      { op: 'replace', path: '/audio/0/metadata/name', value: 'Japanese 5.1' },
      { op: 'replace', path: '/audio/1/encoder', value: 'ac3' },
      { op: 'replace', path: '/audio/1/mixdown', value: '5.1' },
      { op: 'replace', path: '/audio/1/bitrate', value: 640 },
    ])
    await editor.resolveNow()
    steps.push(documentOf())
    // The resolved subtitles are already forced (S1) and default (S2): a name makes the edit.
    expect(
      editor.job?.subtitles?.map((track) => [track.metadata?.forced, track.metadata?.default]),
    ).toEqual([
      [true, false],
      [false, true],
    ])
    editor.patch([{ op: 'replace', path: '/subtitles/1/metadata/name', value: 'English' }])
    resolution = await editor.resolveNow()
    steps.push(documentOf())
    const template = documentOf().template
    expect(
      template.audio_rules?.map((rule) => [rule.settings, rule.metadata?.name_template]),
    ).toEqual([
      [
        expect.objectContaining({ encoder: 'libopus', mixdown: '5.1', bitrate: 448 }),
        'Japanese 5.1',
      ],
      [expect.objectContaining({ encoder: 'ac3', mixdown: '5.1', bitrate: 640 }), null],
    ])
    expect(template.subtitle_rules).toHaveLength(2)
    expect(resolution.columns?.map((column) => column.label)).toEqual([
      'V',
      'A1 jpn TrueHD→Opus 5.1',
      'A2 eng DTS-HD MA→AC-3 5.1',
      'S1 eng Signs & Songs',
      'S2 eng Full',
      'Output name',
    ])
    expect(marks(resolution)[10]).toBe('E11 error A2 missing S1 relaxed')
    expect(marks(resolution).filter((mark) => mark !== 'E11 error A2 missing S1 relaxed')).toEqual(
      [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12].map(
        (n) => `E${String(n).padStart(2, '0')} ${n === 5 ? 'warning' : 'ok'}`,
      ),
    )

    // E11's fix makes A2 optional; a later edit of A1 keeps it optional.
    const fix = rowOf(resolution, 11)
      .issues?.find((found) => found.code === 'batch.track_missing')
      ?.fixes?.find((candidate) => candidate.target === 'template')
    if (fix === undefined) throw new Error('no template fix for E11')
    await editor.applyRowFix(episode(11), fix)
    resolution = await editor.resolveNow()
    steps.push(documentOf())
    expect(documentOf().template.audio_rules?.[1]?.required).toBe(false)
    expect(marks(resolution)[10]).toBe('E11 warning A2 skipped S1 relaxed')
    await vi.waitFor(
      () => expect(editor.job?.audio?.[0]?.metadata?.name).toBe('Japanese 5.1'),
      SOON,
    )
    editor.set('/audio/0/bitrate', 384)
    resolution = await editor.resolveNow()
    steps.push(documentOf())
    expect(documentOf().template.audio_rules?.map((rule) => rule.required)).toEqual([true, false])
    expect(marks(resolution)[10]).toBe('E11 warning A2 skipped S1 relaxed')

    // Undo gives back each step before, redo each step after.
    for (const before of steps.slice(0, -1).toReversed()) {
      editor.undo()
      expect(documentOf()).toEqual(before)
    }
    expect(editor.canUndo).toBe(false)
    for (const after of steps.slice(1)) {
      editor.redo()
      expect(documentOf()).toEqual(after)
    }
    resolution = await editor.resolveNow()

    // A hand pick and No track in E03 change only its row; a template change keeps them.
    let rest = others(resolution, 3)
    editor.pickTrack(episode(3), 'subtitle', 0, 4)
    editor.pickTrack(episode(3), 'audio', 1, null)
    resolution = await editor.resolveNow()
    expect(others(resolution, 3)).toBe(rest)
    const picked = () => rowOf(resolution, 3).matches?.map((match) => [match.status, match.streams])
    expect(picked()).toEqual([
      ['exact', [1]],
      ['skipped', []],
      ['exact', [4]],
      ['exact', [4]],
    ])
    editor.patchTemplate([{ op: 'replace', path: '/video/rate_control/value', value: 24 }])
    resolution = await editor.resolveNow()
    expect(picked()).toEqual([
      ['exact', [1]],
      ['skipped', []],
      ['exact', [4]],
      ['exact', [4]],
    ])

    // A name-field correction changes only E04's output name.
    rest = others(resolution, 4)
    const name = rowOf(resolution, 4).job?.output?.path
    editor.setNameField(episode(4), 'sub_title', 'Signal Fire')
    resolution = await editor.resolveNow()
    expect(others(resolution, 4)).toBe(rest)
    expect(rowOf(resolution, 4).job?.output?.path).toBe(
      String(name).replace(/[^/]*$/, 'Anime.Show.S01E04.Signal Fire.mkv'),
    )

    // A scope-file edit changes only E02's job, shows overriddenAt and survives a template change.
    await editor.showFile(episode(2))
    await editor.setScope('file')
    rest = others(resolution, 2)
    editor.set('/audio/0/bitrate', 320)
    expect(editor.overriddenAt('audio[0].bitrate')).toBe(true)
    expect(editor.overriddenAt('audio[1].bitrate')).toBe(false)
    resolution = await editor.resolveNow()
    expect(others(resolution, 2)).toBe(rest)
    expect(rowOf(resolution, 2).job?.audio?.[0]?.bitrate).toBe(320)
    editor.patchTemplate([
      { op: 'replace', path: '/audio_rules/0/settings/mixdown', value: 'stereo' },
    ])
    resolution = await editor.resolveNow()
    expect(rowOf(resolution, 2).job?.audio?.[0]).toMatchObject({ bitrate: 320, mixdown: 'stereo' })
    await vi.waitFor(() => expect(editor.job?.audio?.[0]?.bitrate).toBe(320), SOON)

    // Reset to group: the group's value again.
    editor.resetToGroup('audio[0].bitrate')
    expect(editor.overriddenAt('audio[0].bitrate')).toBe(false)
    resolution = await editor.resolveNow()
    expect(rowOf(resolution, 2).job?.audio?.[0]?.bitrate).toBe(384)

    // Apply to whole group: the file's value into the template, the override gone, one step.
    editor.set('/audio/0/bitrate', 256)
    await vi.waitFor(() => expect(editor.job?.audio?.[0]?.bitrate).toBe(256), SOON)
    const beforeApply = documentOf()
    await editor.applyToWholeGroup('audio[0].bitrate')
    resolution = await editor.resolveNow()
    expect(documentOf().template.audio_rules?.[0]?.settings).toMatchObject({ bitrate: 256 })
    expect(documentOf().overrides[episode(2)]).toBeUndefined()
    expect((resolution.rows ?? []).map((found) => found.job?.audio?.[0]?.bitrate)).toEqual(
      Array(12).fill(256),
    )
    editor.undo()
    expect(documentOf()).toEqual(beforeApply)

    // An override inside a track whose rule moved is stale in its row, never applied to another track.
    editor.set('/audio/1/bitrate', 96)
    const rule = documentOf().template.audio_rules?.[0] as NonNullable<
      JobTemplate['audio_rules']
    >[number]
    editor.patchTemplate([{ op: 'add', path: '/audio_rules/0', value: rule } as JsonPatchOp])
    resolution = await editor.resolveNow()
    const stale = rowOf(resolution, 2)
    expect(stale.issues?.map((found) => found.code)).toContain('batch.override_stale')
    expect(stale.job?.audio?.map((track) => track.bitrate)).not.toContain(96)
    editor.undo()
    editor.undo()

    // Refused: a per-file field in scope group, a track removed in scope file.
    const kept = documentOf()
    const job = editor.job
    editor.patch([{ op: 'remove', path: '/audio/1' }])
    expect(editor.job).toBe(job)
    await editor.setScope('group')
    const shown = editor.job
    editor.set('/output/path', `${server.output}/mine.mkv`)
    expect(editor.job).toBe(shown)
    expect(editor.editing).toBe(false)
    expect(documentOf()).toEqual(kept)

    // A preset applied to the group replaces the template in one undo step.
    const other = presets.find((candidate) => candidate.id !== editor.presetId) as Preset
    await editor.applyPreset(other.id)
    expect(documentOf()).toEqual({ template: templateOfPreset(other), overrides: kept.overrides })
    expect(editor.presetId).toBe(other.id)
    editor.undo()
    expect(documentOf()).toEqual(kept)
    expect(editor.presetId).toBe(preset.id)

    // The group's state comes back after another file was open.
    await sources.select(episode(7))
    expect(editor.target?.kind).toBe('job')
    await editor.editGroup(season.id)
    expect(documentOf()).toEqual(kept)
    expect(editor.target).toMatchObject({ sourceId: episode(2), scope: 'group' })
    expect(editor.canUndo).toBe(true)

    // Only the newest resolution is kept.
    editor.patchTemplate([{ op: 'replace', path: '/video/rate_control/value', value: 30 }])
    editor.patchTemplate([{ op: 'replace', path: '/video/rate_control/value', value: 31 }])
    await vi.waitFor(() => expect(editor.resolving).toBe(false), SOON)
    expect((editor.resolution?.rows ?? []).map((found) => found.job?.video?.rate_control)).toEqual(
      Array.from({ length: 12 }, () => ({ mode: 'quality', value: 31 })),
    )
  }, 120_000)
})
