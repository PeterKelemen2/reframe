import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { boot, shutdown } from '@/api/boot'
import { ApiError } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { http } from '@/api/testing/serverHelpers'
import type { Preset, SourceEntry } from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'

import { useEditorStore } from './editor'
import { useSourcesStore } from './sources'
import { useToastStore } from './toasts'

const PORT = 8772
const TOKEN = 'sources-test-token'

let server: DevServer

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: [
      '--token',
      TOKEN,
      '--fixtures',
      'season,multitrack',
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

const name = (entry: SourceEntry | null | undefined) => entry?.path.split('/').at(-1)

describe('the sources against a real server', () => {
  it('opens a season folder as one group with its near matches, the first episode in the editor', async () => {
    const sources = useSourcesStore()
    const found = await sources.open([`${server.media}/season`])
    expect(found.map(name)).toEqual(
      Array.from({ length: 12 }, (_, i) => `Show.S01E${String(i + 1).padStart(2, '0')}.Title.mkv`),
    )
    expect(sources.probing).toEqual([])
    expect(sources.entries.every((entry) => entry.source !== null)).toBe(true)

    const groups = sources.grouping?.groups ?? []
    expect(groups.map((group) => [group.name, group.level, group.members?.length])).toEqual([
      ['Show S01', 'standard', 12],
    ])
    const near = (groups[0]?.members ?? []).filter((member) => member.match === 'near')
    expect(near.map((member) => [member.episode, member.differences])).toEqual([
      [5, ['1 extra track (eng AC-3 2.0 "Commentary")']],
      [9, ['1 track missing (eng AAC-LC 2.0 "English Stereo")']],
    ])

    expect(name(sources.active)).toBe('Show.S01E01.Title.mkv')
    expect(useEditorStore().job?.source.path).toBe(sources.active?.path)
  }, 60_000)

  it('refuses a path outside the roots with the server’s problem and opens nothing', async () => {
    const sources = useSourcesStore()
    const refused = await sources.open(['/etc']).catch((error: unknown) => error)
    expect(refused).toBeInstanceOf(ApiError)
    expect((refused as ApiError).problem.code).toBe('path.outside_roots')
    expect(sources.entries).toEqual([])
    expect(sources.probing).toEqual([])
    expect(useToastStore().items.map((toast) => toast.summary)).toEqual([
      'The path is outside the allowed folders',
    ])
  })

  it('keeps the editor’s preset for the next source', async () => {
    const sources = useSourcesStore()
    const editor = useEditorStore()
    await sources.open([
      `${server.media}/multitrack.mkv`,
      `${server.media}/season/Show.S01E02.Title.mkv`,
    ])
    const { presets, default_id } = await http<{ presets: Preset[]; default_id: string | null }>(
      server,
      'GET',
      '/api/presets',
    )
    const other = presets.find(
      (preset) => preset.id !== default_id && preset.id !== editor.presetId,
    )
    if (other === undefined) throw new Error('only one preset')
    await editor.applyPreset(other.id)
    const next = sources.entries.find((entry) => entry.id !== sources.activeId)
    if (next === undefined) throw new Error('one source only')
    await sources.select(next.id)
    expect(editor.job?.source.path).toBe(next.path)
    expect(editor.presetId).toBe(other.id)
  }, 60_000)

  it('forgets a removed source on the server, and probes again what a new server forgot', async () => {
    const sources = useSourcesStore()
    await sources.open([
      `${server.media}/multitrack.mkv`,
      `${server.media}/season/Show.S01E03.Title.mkv`,
    ])
    const [first, second] = sources.entries
    if (first === undefined || second === undefined) throw new Error('two sources expected')
    await sources.remove(second.id)
    const listed = await http<SourceEntry[]>(server, 'GET', '/api/sources')
    expect(listed.map((entry) => entry.id)).not.toContain(second.id)

    // What a restart does to the registry: the server no longer knows the id.
    await http(server, 'DELETE', `/api/sources/${first.id}`)
    await sources.onServerRestart()
    const again = await http<SourceEntry[]>(server, 'GET', '/api/sources')
    expect(again.map((entry) => entry.id)).toContain(first.id)
    expect(sources.activeId).toBe(first.id)
    expect(sources.entries.map((entry) => [entry.id, entry.source !== null])).toEqual([
      [first.id, true],
    ])
  }, 60_000)
})
