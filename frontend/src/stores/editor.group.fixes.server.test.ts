import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { boot, shutdown } from '@/api/boot'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import type { BatchResolution, JobTemplate, JsonPatchOp, Resolution } from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'

import { useEditorStore } from './editor'
import { useSourcesStore } from './sources'
import { useToastStore } from './toasts'

const PORT = 8721
const TOKEN = 'group-fixes-token'
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

function codes(found: Resolution): string[] {
  return (found.issues ?? []).map((issue) => issue.code)
}

function template(): JobTemplate {
  const current = useEditorStore().target
  if (current?.kind !== 'group') throw new Error('no group is edited')
  return current.template
}

/** The season edited as a group. */
async function season() {
  const sources = useSourcesStore()
  const editor = useEditorStore()
  await sources.open([`${server.media}/${SEASON}`])
  const [found] = sources.grouping?.groups ?? []
  if (found === undefined) throw new Error('no group')
  await editor.editGroup(found.id)
  return editor
}

/** The season with 04's audio from E01: two explicit audio rules. */
async function season04() {
  const editor = await season()
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
  expect(template().audio_rules).toHaveLength(2)
  return editor
}

describe('the group target’s review fixes against a real server', () => {
  it('refuses a track edit of the group from E11 (no dub) while the audio follows the defaults', async () => {
    const editor = await season()
    await editor.showFile(episode(11))
    const before = structuredClone(template())
    editor.set('/audio/0/bitrate', 384)
    const resolution = await editor.resolveNow()
    expect(template()).toEqual(before)
    expect(useToastStore().items.map((toast) => toast.summary)).toEqual([
      "E11's tracks do not match the group's",
    ])
    expect(rowOf(resolution, 1).job?.audio).toHaveLength(2)
  }, 120_000)

  it('a file’s track override survives a change of another track, and goes stale when its own track moves', async () => {
    const editor = await season04()
    await editor.showFile(episode(2))
    await editor.setScope('file')
    editor.set('/audio/0/bitrate', 320)
    let resolution = await editor.resolveNow()
    expect(rowOf(resolution, 2).job?.audio?.[0]?.bitrate).toBe(320)

    await editor.setScope('group')
    editor.set('/audio/1/bitrate', 448)
    resolution = await editor.resolveNow()
    expect(template().audio_rules?.[1]?.settings).toMatchObject({ bitrate: 448 })
    const kept = rowOf(resolution, 2)
    expect(codes(kept)).not.toContain('batch.override_stale')
    expect(kept.job?.audio?.map((track) => track.bitrate)).toEqual([320, 448])

    // A stereo AAC of the Japanese track put first in the group: the overridden track moved.
    const first = editor.job?.audio?.[0]
    editor.patch([
      {
        op: 'add',
        path: '/audio/0',
        value: {
          ...first,
          encoder: 'aac',
          mixdown: 'stereo',
          bitrate: 160,
          metadata: { ...first?.metadata, name: 'Japanese Stereo' },
        },
      } as JsonPatchOp,
    ])
    resolution = await editor.resolveNow()
    const stale = rowOf(resolution, 2)
    expect(codes(stale)).toContain('batch.override_stale')
    expect(stale.job?.audio?.map((track) => track.bitrate)).not.toContain(320)
  }, 120_000)

  it('a hand pick stays on its rule when the rule is derived again, and goes stale when the rules move', async () => {
    const editor = await season04()
    // E05's dub rule (A2) takes the commentary #3 by hand.
    editor.pickTrack(episode(5), 'audio', 1, 3)
    let resolution = await editor.resolveNow()
    expect(rowOf(resolution, 5).job?.audio?.map((track) => track.source_stream)).toEqual([1, 3])

    editor.set('/audio/0/bitrate', 384)
    resolution = await editor.resolveNow()
    expect(template().audio_rules?.[0]?.settings).toMatchObject({ bitrate: 384 })
    expect(codes(rowOf(resolution, 5))).not.toContain('batch.override_stale')
    expect(rowOf(resolution, 5).job?.audio?.map((track) => track.source_stream)).toEqual([1, 3])

    // The dub first: the pick's rule index now names the Japanese rule.
    editor.patch([{ op: 'move', from: '/audio/1', path: '/audio/0' } as JsonPatchOp])
    resolution = await editor.resolveNow()
    expect(template().audio_rules?.map((rule) => rule.selector.languages)).toEqual([['en'], ['ja']])
    const e05 = rowOf(resolution, 5)
    expect(codes(e05)).toContain('batch.override_stale')
    expect(e05.job?.audio?.map((track) => track.source_stream)).toEqual([2, 1])
  }, 120_000)

  it('an earlier episode opened while the group is edited: the group of 12 keeps the edits', async () => {
    const sources = useSourcesStore()
    const editor = useEditorStore()
    await sources.open([`${server.media}/${SEASON}`])
    const first = sources.entries.find((entry) => entry.id === episode(1))?.path as string
    await sources.remove(episode(1))
    await vi.waitFor(() => expect(sources.grouping?.groups?.[0]?.members).toHaveLength(11), SOON)
    const [eleven] = sources.grouping?.groups ?? []
    if (eleven === undefined) throw new Error('no group')
    await editor.editGroup(eleven.id)
    editor.set('/video/rate_control/value', 30)
    await editor.resolveNow()

    await sources.open([first])
    await vi.waitFor(() => expect(sources.grouping?.groups?.[0]?.members).toHaveLength(12), SOON)
    const twelve = sources.grouping?.groups?.[0]
    expect(twelve?.id).not.toBe(eleven.id)
    expect(editor.target).toMatchObject({ kind: 'group', groupId: twelve?.id })
    expect(template().video?.rate_control).toEqual({ mode: 'quality', value: 30 })
    expect(editor.canUndo).toBe(true)
    const resolution = await editor.resolveNow()
    expect(resolution.rows?.map((found) => found.job?.video?.rate_control)).toEqual(
      Array.from({ length: 12 }, () => ({ mode: 'quality', value: 30 })),
    )
  }, 120_000)
})
