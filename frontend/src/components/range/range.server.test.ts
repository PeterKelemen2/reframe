import { createPinia, setActivePinia } from 'pinia'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { configureClient } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import type { EncodePlan, JobSettings, SourceEntry, ValidationIssue } from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'

import { convertRange, type Range, rangeSeconds } from './range'
import { RANGE_PATHS } from './useRange'

const PORT = 8716

let server: DevServer
let entry: SourceEntry

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: ['--fixtures', 'chapters', ...(tools === null ? [] : ['--tools-dir', tools])],
  })
  const probe = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
    paths: [`${server.media}/chapters.mkv`],
  })
  await endedTask(server, probe.task_id)
  entry = (await http<SourceEntry[]>(server, 'GET', '/api/sources'))[0]!
}, 120_000)

afterAll(async () => {
  await server.stop()
})

beforeEach(() => {
  setActivePinia(createPinia())
  configureClient({ baseUrl: server.url, token: server.token })
  useSourcesStore().entries = [entry]
})

async function opened() {
  const editor = useEditorStore()
  await editor.open(entry.id)
  return editor
}

async function validate(job: JobSettings): Promise<ValidationIssue[]> {
  const issues = await http<ValidationIssue[]>(server, 'POST', '/api/jobs/validate', { job })
  return issues.filter((issue) => issue.code.startsWith('range.'))
}

/** The seek and the length of the encode step, in seconds; `null` for one it leaves out. */
async function cut(
  job: JobSettings,
): Promise<{ ss: number | null; t: number | null; plan: EncodePlan }> {
  const plan = await http<EncodePlan>(server, 'POST', '/api/jobs/plan', { job })
  const step = plan.steps.find((found) => found.kind === 'encode')
  const argv = (step?.argv ?? []).filter((arg): arg is string => typeof arg === 'string')
  const after = (flag: string) => {
    const at = argv.indexOf(flag)
    return at < 0 ? null : Number(argv[at + 1])
  }
  return { ss: after('-ss'), t: after('-t'), plan }
}

/** Runs `each` for one item after the other: edits of one editor that must come in turn. */
async function inTurn<T>(items: readonly T[], each: (item: T) => Promise<void>): Promise<void> {
  const [first, ...rest] = items
  if (first === undefined) return
  await each(first)
  await inTurn(rest, each)
}

describe('the Range selector against a real server and chapters.mkv', () => {
  it('reads the fixture’s chapters and frame rate as the plan expects', () => {
    const source = entry.source!
    expect(source.chapters?.map((chapter) => [chapter.title, chapter.start, chapter.end])).toEqual([
      ['Opening', 0, 1],
      ['Part One', 1, 2.5],
      ['Part Two', 2.5, 4],
      ['Credits', 4, 5],
    ])
    expect(source.video?.[0]?.avg_frame_rate).toEqual({ num: 25, den: 1 })
  })

  it('cuts chapters 2–3 at their times, and seconds and frames from the same span cut the same', async () => {
    const editor = await opened()
    const source = entry.source!
    editor.setRange(convertRange(editor.range, 'chapters', source))
    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    const job = editor.job!
    expect(job.range).toEqual({ kind: 'chapters', start: 2, end: 3 })
    expect(await validate(job)).toEqual([])
    const chapters = await cut(job)
    expect(chapters).toMatchObject({ ss: 1, t: 3 })
    expect(chapters.plan.expected_duration).toBeCloseTo(3, 6)
    expect(rangeSeconds(job, source)).toBe(3)

    await inTurn(['time', 'frames'] as const, async (kind) => {
      editor.setRange(convertRange(editor.range, kind, source))
      const converted = editor.job!
      expect(await validate(converted)).toEqual([])
      expect(await cut(converted)).toMatchObject({ ss: 1, t: 3 })
      expect(rangeSeconds(converted, source)).toBe(3)
    })
    expect(editor.job?.range).toEqual({ kind: 'frames', start: 25, end: 100 })
    editor.setRange(convertRange(editor.range, 'chapters', source))
    expect(editor.job?.range).toEqual({ kind: 'chapters', start: 2, end: 3 })
  })

  it('gives the length the plan encodes when the range ends after the source', async () => {
    const editor = await opened()
    const source = entry.source!
    const ranges: Range[] = [
      { kind: 'time', start: 4, end: 600 },
      { kind: 'chapters', start: 3, end: 9 },
    ]
    await inTurn(ranges, async (range) => {
      editor.setRange(range)
      const { plan } = await cut(editor.job!)
      expect(rangeSeconds(editor.job!, source)).toBeCloseTo(plan.expected_duration, 3)
    })
  })

  it('gets its issues on the paths the popover shows, and their fixes apply', async () => {
    const editor = await opened()
    const cases: [Range, string, string][] = [
      [{ kind: 'chapters', start: 2, end: 9 }, 'range.end_beyond', 'range.end'],
      [{ kind: 'chapters', start: 3, end: 2 }, 'range.outside', 'range'],
      [{ kind: 'chapters', start: 6, end: 7 }, 'range.outside', 'range.start'],
      [{ kind: 'time', start: 10, end: null }, 'range.outside', 'range.start'],
      [{ kind: 'time', start: 1, end: 60 }, 'range.end_beyond', 'range.end'],
      [{ kind: 'frames', start: 50, end: 25 }, 'range.outside', 'range'],
    ]
    await inTurn(cases, async ([range, code, path]) => {
      editor.setRange(range)
      const issues = await validate(editor.job!)
      expect(issues.map((found) => [found.code, found.path])).toEqual([[code, path]])
      expect(RANGE_PATHS).toContain(path)
      const fix = issues[0]!.fixes?.[0]
      expect(fix?.target).toBe('job')
      await editor.applyFix(fix!)
      expect(await validate(editor.job!)).toEqual([])
    })
    // The fixes: the last chapter, the end of the source, or the whole source.
    editor.setRange({ kind: 'chapters', start: 2, end: 9 })
    await editor.applyFix((await validate(editor.job!))[0]!.fixes![0]!)
    expect(editor.job?.range).toEqual({ kind: 'chapters', start: 2, end: 4 })
  })
})
