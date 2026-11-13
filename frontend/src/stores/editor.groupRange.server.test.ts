// A chapter range on one file of a group, in scope `group`, against the real server: the shown
// job that the naming preview and the command drawer read has it, the other files do not.
import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { boot, shutdown } from '@/api/boot'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { http } from '@/api/testing/serverHelpers'
import type { EncodePlan, JobSettings, NameResult, ValidationIssue } from '@/api/types'
import type { Range } from '@/components/range/range'
import { copyAs } from '@/components/naming/testing/releases.mjs'
import { pinnedTools } from '@/editor/testing/tools.mjs'

import { useEditorStore } from './editor'
import { useSourcesStore } from './sources'

const PORT = 8703
const TOKEN = 'group-range-token'
const SEASON = 'Chap.Show.S01.BluRay.x264-GRP'
const EPISODES = ['Alpha', 'Beta', 'Gamma'].map(
  (title, index) => `${SEASON}/Chap.Show.S01E0${index + 1}.${title}.BluRay.x264-GRP.mkv`,
)
const TEMPLATE = '{name} S{season:02}E{episode:02} {chapters}'
const CHAPTERS: Range = { kind: 'chapters', start: 2, end: 3 }
const WHOLE: Range = { kind: 'full' }
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
      'chapters',
      ...(tools === null ? [] : ['--tools-dir', tools]),
    ],
  })
  await copyAs(`${server.media}/chapters.mkv`, server.media, EPISODES)
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
  const entry = useSourcesStore().entries.find((found) => found.path.includes(`E0${number}`))
  if (entry === undefined) throw new Error(`no E0${number}`)
  return entry.id
}

/** The file name `naming/preview` gives `job` in the file `sourceId`, with the group's naming. */
async function nameOf(job: JobSettings, sourceId: string): Promise<string> {
  const [result] = await http<NameResult[]>(server, 'POST', '/api/naming/preview', {
    source_ids: [sourceId],
    job,
    naming: useEditorStore().currentTemplate?.naming,
  })
  return result?.relative_path ?? ''
}

/** The seek and the length of `job`'s encode step, in seconds; `null` for one it leaves out. */
async function cut(job: JobSettings): Promise<{ ss: number | null; t: number | null }> {
  const plan = await http<EncodePlan>(server, 'POST', '/api/jobs/plan', { job })
  const step = plan.steps.find((found) => found.kind === 'encode')
  const argv = (step?.argv ?? []).filter((arg): arg is string => typeof arg === 'string')
  const after = (flag: string) => {
    const at = argv.indexOf(flag)
    return at < 0 ? null : Number(argv[at + 1])
  }
  return { ss: after('-ss'), t: after('-t') }
}

async function rangeIssues(job: JobSettings): Promise<string[]> {
  const issues = await http<ValidationIssue[]>(server, 'POST', '/api/jobs/validate', { job })
  return issues.filter((issue) => issue.code.startsWith('range.')).map((issue) => issue.code)
}

describe('a range in a group’s scope group, against a real server', () => {
  it('names and cuts the shown file’s chapters 2–3, and leaves the other files whole', async () => {
    const sources = useSourcesStore()
    const editor = useEditorStore()
    await sources.open([`${server.media}/${SEASON}`])
    const [season] = sources.grouping?.groups ?? []
    if (season === undefined) throw new Error('no group')
    expect(season.members).toHaveLength(3)
    await editor.editGroup(season.id)
    expect(editor.target).toMatchObject({ scope: 'group', sourceId: episode(1) })

    editor.set('/output/naming/template', TEMPLATE)
    await editor.resolveNow()
    await vi.waitFor(() => expect(editor.draft?.naming?.relative_path).toMatch(/1-4/), SOON)
    expect(editor.currentTemplate?.naming?.episode_template).toBe(TEMPLATE)
    expect(await nameOf(editor.job!, episode(1))).toBe('Chap.Show S01E01 1-4.mkv')

    editor.setRange(CHAPTERS)
    // The server's shown job, not only the store's own copy, has the range.
    await vi.waitFor(() => expect(editor.draft?.job?.range).toEqual(CHAPTERS), SOON)
    const shown = editor.job!
    expect(shown.range).toEqual(CHAPTERS)
    // The Summary's output name in scope group is the shown row's.
    expect(editor.draft?.naming?.relative_path).toBe('Chap.Show S01E01 2-3.mkv')
    expect(await nameOf(shown, episode(1))).toBe('Chap.Show S01E01 2-3.mkv')
    expect(await cut(shown)).toEqual({ ss: 1, t: 3 })
    expect(await rangeIssues(shown)).toEqual([])
    // A range past the last chapter is a warning on the shown job itself.
    editor.setRange({ kind: 'chapters', start: 2, end: 9 })
    await vi.waitFor(() => expect(editor.draft?.job?.range).toMatchObject({ end: 9 }), SOON)
    expect(await rangeIssues(editor.job!)).toEqual(['range.end_beyond'])
    editor.undo()
    await vi.waitFor(() => expect(editor.draft?.job?.range).toEqual(CHAPTERS), SOON)

    const resolution = await editor.resolveNow()
    const rows = resolution.rows ?? []
    expect(rows.map((row) => row.job?.range)).toEqual([CHAPTERS, WHOLE, WHOLE])
    expect(rows.map((row) => row.job?.output?.path?.split('/').at(-1))).toEqual([
      'Chap.Show S01E01 2-3.mkv',
      'Chap.Show S01E02 1-4.mkv',
      'Chap.Show S01E03 1-4.mkv',
    ])
    expect(await cut(rows[1]!.job as JobSettings)).toEqual({ ss: null, t: null })
    // The range never went into the template.
    expect(editor.target).not.toHaveProperty('template.range')

    await editor.showFile(episode(2))
    await vi.waitFor(() => expect(editor.target?.sourceId).toBe(episode(2)), SOON)
    expect(editor.job?.range).toEqual(WHOLE)
    expect(await nameOf(editor.job!, episode(2))).toBe('Chap.Show S01E02 1-4.mkv')
  })
})
