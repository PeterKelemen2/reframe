import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { FakeServer, type Recorded } from '@/api/testing/fakes'
import type {
  BatchGroup,
  BatchRun,
  JobDraft,
  JobTemplate,
  JsonPatchOp,
  Resolution,
} from '@/api/types'
import type { Range } from '@/components/range/range'
import { applyOps } from '@/editor/patch'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'

import { useEditorStore } from './editor'
import { useSourcesStore } from './sources'
import { useToastStore } from './toasts'

const PRESET = 'h265-mkv-1080p'
const IDS = ['e1', 'e2']
const CHAPTERS: Range = { kind: 'chapters', start: 2, end: 3 }
const TIME: Range = { kind: 'time', start: 1, end: 4 }

function pathOf(id: string): string {
  return `/media/${id}.mkv`
}

function body<T>(request: Recorded | undefined): T {
  return request?.body as T
}

/** The fake drafts the source with the preset, always over the whole source. */
function draftFor(sourceId: string, presetId: string | null): JobDraft {
  const job = sampleJob()
  job.source.path = pathOf(sourceId)
  job.preset_id = presetId ?? PRESET
  if (presetId === 'h264') job.video!.encoder = 'libx264'
  return sampleDraft(job)
}

/** The fake resolution: the template's video, then the `/job` part of the override. */
function row(template: JobTemplate, id: string, override: JsonPatchOp[] = []): Resolution {
  let job = sampleJob()
  job.source.path = pathOf(id)
  job.video = { ...template.video!, metadata: job.video!.metadata }
  const own: JsonPatchOp[] = []
  for (const op of override) {
    if (op.path.startsWith('/job/')) own.push({ ...op, path: op.path.slice(4) })
  }
  job = applyOps(job, own)
  return { path: pathOf(id), job, matches: [], issues: [], status: 'ok', override }
}

type ResolveBody = {
  template: JobTemplate
  source_ids: string[]
  overrides: Record<string, JsonPatchOp[]>
}

function group(): BatchGroup {
  return {
    id: 'g1',
    name: 'Show S01',
    level: 'standard',
    representative: pathOf('e1'),
    fingerprint: { level: 'standard', tracks: [], digest: 'd' },
    members: IDS.map((member, index) => ({
      path: pathOf(member),
      match: 'exact',
      episode: index + 1,
    })),
  }
}

async function flush(): Promise<void> {
  await vi.advanceTimersByTimeAsync(5)
}

let server: FakeServer

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  server = new FakeServer()
    .on('POST /api/jobs/draft', (request) => {
      const sent = body<{ source_id: string; preset_id: string | null }>(request)
      return draftFor(sent.source_id, sent.preset_id)
    })
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets', { presets: [samplePreset()], default_id: PRESET })
    .on(`GET /api/presets/${PRESET}`, samplePreset())
    .on('GET /api/presets/h264', { ...samplePreset(), id: 'h264', name: 'H.264' })
    .on('POST /api/batch/resolve', (request) => {
      const { template, source_ids, overrides } = body<ResolveBody>(request)
      return {
        columns: [],
        rows: source_ids.map((id) => row(template, id, overrides[id])),
        issues: [],
      }
    })
    .on('POST /api/batch/resolve-run', (request): BatchRun => {
      const { template, source_ids, overrides } = body<ResolveBody>(request)
      return {
        grouping: { groups: [], issues: [] },
        resolutions: [
          {
            columns: [],
            rows: source_ids.map((id) => row(template, id, overrides[id])),
            issues: [],
          },
        ],
      }
    })
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const sources = useSourcesStore()
  sources.entries = [...IDS, 'movie'].map((id) => ({ id, path: pathOf(id), source: null }))
  sources.grouping = { groups: [group()], issues: [] }
})

afterEach(() => {
  vi.useRealTimers()
})

async function opened() {
  const editor = useEditorStore()
  await editor.open('movie')
  await flush()
  return editor
}

async function edited(scope: 'group' | 'file' = 'group') {
  const editor = useEditorStore()
  await editor.editGroup('g1')
  await flush()
  if (scope === 'file') {
    await editor.setScope('file')
    await flush()
  }
  return editor
}

function overridesOf(editor: ReturnType<typeof useEditorStore>): Record<string, JsonPatchOp[]> {
  const current = editor.target
  if (current?.kind !== 'group') throw new Error('no group')
  return current.overrides
}

describe('the range of a job', () => {
  it('is one replace on /range per change, each its own undo step', async () => {
    const editor = await opened()
    editor.set('/video/rate_control/value', 19, { coalesce: 'quality' })
    editor.setRange(CHAPTERS)
    editor.set('/video/rate_control/value', 20, { coalesce: 'quality' })
    editor.setRange(TIME)
    expect(editor.job?.range).toEqual(TIME)
    expect(editor.range).toEqual(TIME)

    editor.undo()
    expect(editor.job?.range).toEqual(CHAPTERS)
    expect(editor.get('/video/rate_control/value')).toBe(20)
    editor.undo()
    expect(editor.get('/video/rate_control/value')).toBe(19)
    expect(editor.job?.range).toEqual(CHAPTERS)
    editor.undo()
    expect(editor.job?.range).toEqual({ kind: 'full' })
    expect(editor.get('/video/rate_control/value')).toBe(19)
  })

  it('adds no undo step for the range it already has, and never says it is overridden', async () => {
    const editor = await opened()
    editor.setRange({ kind: 'full' })
    expect(editor.canUndo).toBe(false)
    editor.setRange(CHAPTERS)
    editor.setRange({ kind: 'chapters', start: 2, end: 3 })
    editor.undo()
    expect(editor.canUndo).toBe(false)
    expect(editor.rangeOverridden).toBe(false)
  })

  it('keeps its range when a preset is picked, and undo brings both back', async () => {
    const editor = await opened()
    editor.setRange(CHAPTERS)
    await editor.applyPreset('h264')
    await flush()
    expect(editor.get('/video/encoder')).toBe('libx264')
    expect(editor.job?.range).toEqual(CHAPTERS)
    editor.undo()
    expect(editor.get('/video/encoder')).toBe('libx265')
    expect(editor.job?.range).toEqual(CHAPTERS)
    editor.undo()
    expect(editor.job?.range).toEqual({ kind: 'full' })
  })

  it('keeps the draft’s own job when there is no range to keep', async () => {
    const editor = await opened()
    await editor.applyPreset('h264')
    expect(editor.draft?.job).toBe(editor.job)
  })
})

describe('the range in a group', () => {
  it('in scope group is the shown file’s override: no toast, the template has none', async () => {
    const editor = await edited()
    const template = (editor.target as { template: JobTemplate }).template
    editor.setRange(CHAPTERS)
    await flush()

    expect(useToastStore().items).toEqual([])
    expect(overridesOf(editor)).toEqual({
      e1: [{ op: 'replace', path: '/job/range', value: CHAPTERS }],
    })
    expect((editor.target as { template: JobTemplate }).template).toEqual(template)
    expect(editor.rangeOverridden).toBe(true)
    // The shown job of scope group leaves the override out; the range is the file's.
    expect(editor.job?.range).toEqual({ kind: 'full' })
    expect(editor.range).toEqual(CHAPTERS)

    editor.setRange(TIME)
    expect(overridesOf(editor).e1).toEqual([{ op: 'replace', path: '/job/range', value: TIME }])
    editor.undo()
    expect(editor.range).toEqual(CHAPTERS)
    editor.undo()
    expect(overridesOf(editor)).toEqual({})
    expect(editor.rangeOverridden).toBe(false)
  })

  it('in scope file shows the range in the job at once', async () => {
    const editor = await edited('file')
    editor.setRange(CHAPTERS)
    expect(editor.job?.range).toEqual(CHAPTERS)
    expect(editor.range).toEqual(CHAPTERS)
    await flush()
    expect(editor.job?.range).toEqual(CHAPTERS)
    expect(editor.rangeOverridden).toBe(true)
  })

  it('belongs to the shown file only', async () => {
    const editor = await edited()
    editor.setRange(CHAPTERS)
    await editor.showFile('e2')
    await flush()
    expect(editor.rangeOverridden).toBe(false)
    expect(editor.range).toEqual({ kind: 'full' })
    expect(Object.keys(overridesOf(editor))).toEqual(['e1'])
  })

  it('keeps the file’s other overrides when it changes or is reset', async () => {
    const editor = await edited()
    editor.setNameField('e1', 'episode', '7')
    editor.setRange(CHAPTERS)
    const name = { op: 'add', path: '/job/output/naming/field_overrides/episode', value: '7' }
    expect(overridesOf(editor).e1).toEqual([
      name,
      { op: 'replace', path: '/job/range', value: CHAPTERS },
    ])
    editor.resetRangeToGroup()
    expect(overridesOf(editor).e1).toEqual([name])
  })

  it('reset to group is one undo step, and drops a fix’s whole-source override too', async () => {
    const editor = await edited('file')
    editor.setRange(CHAPTERS)
    editor.resetRangeToGroup()
    expect(editor.rangeOverridden).toBe(false)
    expect(editor.job?.range).toEqual({ kind: 'full' })
    editor.undo()
    expect(editor.range).toEqual(CHAPTERS)

    // A row fix ("Encode the whole source") leaves an override that says what the group says.
    await editor.applyRowFix('e1', {
      label: 'Encode the whole source',
      target: 'job',
      patch: [{ op: 'replace', path: '/range', value: { kind: 'full' } }],
    })
    await flush()
    expect(editor.rangeOverridden).toBe(true)
    expect(editor.range).toEqual({ kind: 'full' })
    editor.resetRangeToGroup()
    expect(overridesOf(editor)).toEqual({})
  })

  it('a whole source picked by hand leaves no override', async () => {
    const editor = await edited()
    editor.setRange(CHAPTERS)
    editor.setRange({ kind: 'full' })
    expect(overridesOf(editor)).toEqual({})
    expect(editor.rangeOverridden).toBe(false)
  })

  it('applies a fix’s change of the end on top of the file’s range', async () => {
    const editor = await edited()
    editor.setRange({ kind: 'chapters', start: 2, end: 9 })
    await editor.applyRowFix('e1', {
      label: 'End at chapter 4',
      target: 'job',
      patch: [{ op: 'replace', path: '/range/end', value: 4 }],
    })
    await flush()
    expect(editor.range).toEqual({ kind: 'chapters', start: 2, end: 4 })
  })
})

describe('setRange', () => {
  it('needs an open job', () => {
    expect(() => useEditorStore().setRange(CHAPTERS)).toThrow(/no job is open/)
  })

  it('does not keep the caller’s object', async () => {
    const editor = await edited()
    const chosen: Range = { kind: 'time', start: 1, end: 2 }
    editor.setRange(chosen)
    chosen.start = 0
    expect(editor.range).toEqual({ kind: 'time', start: 1, end: 2 })
    expect(Object.isFrozen(chosen)).toBe(false)
  })
})
