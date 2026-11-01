import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, problem, type Recorded } from '@/api/testing/fakes'
import type {
  BatchGroup,
  BatchRun,
  JobSettings,
  JobTemplate,
  JsonPatchOp,
  MediaSource,
  Preset,
  Resolution,
} from '@/api/types'
import { applyOps } from '@/editor/patch'
import { sampleJob, samplePreset } from '@/editor/testing/samples'

import { useValidation } from '@/composables/useValidation'

import { EDIT_DEBOUNCE, useEditorStore } from './editor'
import { templateOfPreset } from './presets'
import { useSourcesStore } from './sources'
import { useToastStore } from './toasts'
import { useValidationStore } from './validation'

const PRESET = 'h265-mkv-1080p'
const IDS = ['e1', 'e2', 'e3']

function pathOf(id: string): string {
  return `/media/${id}.mkv`
}

function group(id = 'g1', ids = IDS): BatchGroup {
  return {
    id,
    name: 'Show S01',
    level: 'standard',
    representative: pathOf(ids[0] ?? ''),
    fingerprint: { level: 'standard', tracks: [], digest: 'd' },
    members: ids.map((member, index) => ({
      path: pathOf(member),
      match: 'exact',
      episode: index + 1,
    })),
  }
}

/**
 * The fake server's resolution: the job takes the template's video and output options, and
 * then the `/job` part of the override.
 */
function row(template: JobTemplate, id: string, override: JsonPatchOp[] = []): Resolution {
  let job = sampleJob()
  job.source.path = pathOf(id)
  job.output = { ...job.output!, ...template.output, path: `/out/${id}.mkv` }
  job.video = { ...template.video!, metadata: job.video!.metadata }
  const own: JsonPatchOp[] = []
  for (const op of override)
    if (op.path.startsWith('/job/')) own.push({ ...op, path: op.path.slice(4) })
  job = applyOps(job, own)
  return { path: pathOf(id), job, matches: [], issues: [], status: 'ok', override }
}

/** The fake derive: the video section of the job into the base. */
function derive(sent: { job: JobSettings; sections: string[]; base: JobTemplate }): JobTemplate {
  return sent.sections.includes('video')
    ? { ...sent.base, video: { ...sent.job.video!, metadata: sent.base.video?.metadata } }
    : sent.base
}

function h264(): Preset {
  const preset = samplePreset()
  return { ...preset, id: 'h264', name: 'H.264', video: { ...preset.video!, encoder: 'libx264' } }
}

function body<T>(request: Recorded | undefined): T {
  return request?.body as T
}

/**
 * Lets the fake answers, and the requests they lead to, run. A zero-delay timer set while the
 * fake clock ticks is due a millisecond later.
 */
async function flush(): Promise<void> {
  await vi.advanceTimersByTimeAsync(5)
}

type ResolveBody = {
  template: JobTemplate
  source_ids: string[]
  overrides: Record<string, JsonPatchOp[]>
  level?: string
}

async function edited() {
  const editor = useEditorStore()
  await editor.editGroup('g1')
  await flush()
  return editor
}

function documentOf(editor: ReturnType<typeof useEditorStore>) {
  const current = editor.target
  if (current?.kind !== 'group') throw new Error('no group')
  return structuredClone({ template: current.template, overrides: current.overrides })
}

/** An edit of scope `group`, derived into the template. */
async function derivedEdit(editor: ReturnType<typeof useEditorStore>, ops: JsonPatchOp[]) {
  editor.patch(ops)
  await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
  await flush()
}

async function inFile() {
  const editor = await edited()
  await editor.setScope('file')
  await flush()
  return editor
}

async function withRules() {
  const editor = await edited()
  editor.patchTemplate([
    {
      op: 'replace',
      path: '/audio_rules',
      value: [{ selector: { kind: 'audio', languages: ['ja'] }, settings: { kind: 'audio' } }],
    },
  ])
  return editor
}

describe('the editor store, group target', () => {
  let server: FakeServer

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    server = new FakeServer()
      .on('POST /api/jobs/draft', (request) => {
        const { source_id, preset_id } = body<{ source_id: string; preset_id: string | null }>(
          request,
        )
        const preset = preset_id === 'h264' ? h264() : samplePreset()
        const job = {
          ...(row(templateOfPreset(preset), source_id).job as JobSettings),
          preset_id: preset.id,
        }
        return { job, decisions: [], subtitle_decisions: [], naming: null, issues: [], notes: [] }
      })
      .on('POST /api/presets/diff', [])
      .on('GET /api/presets', { presets: [samplePreset(), h264()], default_id: PRESET })
      .on(`GET /api/presets/${PRESET}`, samplePreset())
      .on('GET /api/presets/h264', h264())
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
              columns: [{ kind: 'video', label: 'V', defaults: false }],
              rows: source_ids.map((id) => row(template, id, overrides[id])),
              issues: [],
            },
          ],
        }
      })
      .on('POST /api/batch/derive', (request) => derive(body(request)))
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    const sources = useSourcesStore()
    sources.entries = [...IDS, 'other'].map((id) => ({ id, path: pathOf(id), source: null }))
    sources.grouping = { groups: [group()], issues: [] }
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function requests(route: string): Recorded[] {
    return server.requests.filter((request) => `${request.method} ${request.path}` === route)
  }

  describe('editGroup', () => {
    it('starts from the editor preset as a template, shows the representative and asks for the matrix', async () => {
      const editor = await edited()
      const preset = samplePreset()
      expect(editor.target).toMatchObject({
        kind: 'group',
        groupId: 'g1',
        sourceId: 'e1',
        scope: 'group',
        presetId: PRESET,
        overrides: {},
        template: templateOfPreset(preset),
      })
      expect(Object.keys((editor.target as { template: object }).template)).not.toContain('name')
      expect(editor.job?.source.path).toBe(pathOf('e1'))
      expect(editor.draft?.job).toBe(editor.job)
      expect(useSourcesStore().activeId).toBe('e1')
      expect(editor.group?.id).toBe('g1')
      expect(editor.currentTemplate).toEqual(templateOfPreset(preset))
      expect(body<ResolveBody>(requests('POST /api/batch/resolve')[0])).toEqual({
        template: templateOfPreset(preset),
        source_ids: ['e1'],
        overrides: {},
      })
      expect(body<ResolveBody>(requests('POST /api/batch/resolve-run')[0])).toMatchObject({
        source_ids: IDS,
        level: 'standard',
        overrides: {},
      })
      expect(editor.resolution?.rows?.map((found) => found.path)).toEqual(IDS.map(pathOf))
      expect(editor.resolving).toBe(false)
    })

    it('takes the open job’s preset', async () => {
      const editor = useEditorStore()
      await editor.open('other', 'h264')
      await editor.editGroup('g1')
      expect(editor.presetId).toBe('h264')
      expect((editor.target as { template: JobTemplate }).template.video?.encoder).toBe('libx264')
    })

    it('brings the state of a group back after another file was open', async () => {
      const editor = await edited()
      await derivedEdit(editor, [{ op: 'replace', path: '/video/encoder', value: 'libx264' }])
      editor.setNameField('e2', 'episode', '2')
      await editor.setScope('file')
      await editor.showFile('e3')
      const before = documentOf(editor)

      await useSourcesStore().select('other')
      expect(editor.target?.kind).toBe('job')
      expect(editor.canUndo).toBe(false)
      expect(editor.resolution).toBeNull()

      await editor.editGroup('g1')
      expect(documentOf(editor)).toEqual(before)
      expect(editor.target).toMatchObject({ sourceId: 'e3', scope: 'file' })
      expect(useSourcesStore().activeId).toBe('e3')
      editor.undo()
      editor.undo()
      expect(documentOf(editor).template.video?.encoder).toBe('libx265')
    })

    it('shows the representative when the kept shown file left the group', async () => {
      const editor = await edited()
      await editor.showFile('e3')
      await editor.open('other')
      useSourcesStore().grouping = { groups: [group('g1', ['e1', 'e2'])], issues: [] }
      await editor.editGroup('g1')
      expect(editor.target?.sourceId).toBe('e1')
    })
  })

  describe('an edit of scope group', () => {
    it('shows at once, waits, then derives the touched sections into the template as one undo step', async () => {
      const editor = await edited()
      const before = documentOf(editor)
      editor.set('/video/encoder', 'libx264', { coalesce: 'encoder' })
      editor.set('/video/preset', 'veryslow', { coalesce: 'encoder' })
      expect(editor.job?.video?.preset).toBe('veryslow')
      expect(editor.editing).toBe(true)
      expect(editor.canUndo).toBe(false)
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 1)
      expect(requests('POST /api/batch/derive')).toHaveLength(0)
      await vi.advanceTimersByTimeAsync(1)
      await flush()

      expect(requests('POST /api/batch/derive')).toHaveLength(1)
      expect(body(requests('POST /api/batch/derive')[0])).toMatchObject({
        source_id: 'e1',
        sections: ['video'],
        base: before.template,
      })
      const after = documentOf(editor)
      expect(after.template.video).toMatchObject({ encoder: 'libx264', preset: 'veryslow' })
      expect(editor.editing).toBe(false)
      expect(editor.canUndo).toBe(true)
      // The group resolves again with the new template.
      expect(body<ResolveBody>(requests('POST /api/batch/resolve-run').at(-1)).template).toEqual(
        after.template,
      )

      editor.undo()
      expect(documentOf(editor)).toEqual(before)
      expect(editor.canUndo).toBe(false)
      editor.redo()
      expect(documentOf(editor)).toEqual(after)
    })

    it('copies the output options into the template', async () => {
      const editor = await edited()
      await derivedEdit(editor, [{ op: 'replace', path: '/output/container', value: 'mp4' }])
      expect(documentOf(editor).template.output?.container).toBe('mp4')
      expect(documentOf(editor).template.output).not.toHaveProperty('path')
    })

    it('refuses a field the template cannot hold: a toast, and nothing changes', async () => {
      const editor = await edited()
      const before = documentOf(editor)
      const job = editor.job
      editor.set('/output/path', '/out/mine.mkv')
      editor.set('/chapters/names', ['Intro'])
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(editor.job).toBe(job)
      expect(documentOf(editor)).toEqual(before)
      expect(editor.canUndo).toBe(false)
      expect(editor.editing).toBe(false)
      expect(requests('POST /api/batch/derive')).toHaveLength(0)
      expect(useToastStore().items.map((toast) => toast.summary)).toEqual([
        'The output path is set per file',
        'Chapter names is set per file',
      ])
      expect(useToastStore().items[0]?.detail).toContain('This file only')
    })

    it('derives an edit made while a derive is on its way after it, from the newest job', async () => {
      const slow = deferred<JobTemplate>()
      let first = true
      server.on('POST /api/batch/derive', (request) => {
        if (!first) return derive(body(request))
        first = false
        return slow.promise
      })
      const editor = await edited()
      editor.set('/video/encoder', 'libx264')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      editor.set('/video/preset', 'veryslow')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(requests('POST /api/batch/derive')).toHaveLength(1)
      const base = documentOf(editor).template
      slow.resolve(derive(body(requests('POST /api/batch/derive')[0])))
      await flush()
      await flush()

      expect(requests('POST /api/batch/derive')).toHaveLength(2)
      expect(
        body<{ job: JobSettings }>(requests('POST /api/batch/derive')[1]).job.video,
      ).toMatchObject({
        encoder: 'libx264',
        preset: 'veryslow',
      })
      expect(documentOf(editor).template.video).toMatchObject({
        encoder: 'libx264',
        preset: 'veryslow',
      })
      expect(base.video?.encoder).toBe('libx265')
      editor.undo()
      editor.undo()
      expect(documentOf(editor).template).toEqual(base)
    })

    it('derives again when the template changed while its derive was on its way', async () => {
      const slow = deferred<JobTemplate>()
      let first = true
      server.on('POST /api/batch/derive', (request) => {
        if (!first) return derive(body(request))
        first = false
        return slow.promise
      })
      const editor = await edited()
      editor.set('/video/encoder', 'libx264')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      editor.patchTemplate([{ op: 'replace', path: '/output/container', value: 'mp4' }])
      slow.resolve(derive(body(requests('POST /api/batch/derive')[0])))
      await flush()
      await flush()
      expect(documentOf(editor).template).toMatchObject({
        output: { container: 'mp4' },
        video: { encoder: 'libx264' },
      })
    })

    it('drops a waiting edit on undo, and undoes nothing else', async () => {
      const editor = await edited()
      await derivedEdit(editor, [{ op: 'replace', path: '/video/encoder', value: 'libx264' }])
      const before = documentOf(editor)
      const job = editor.job
      editor.set('/video/preset', 'veryslow')
      editor.undo()
      expect(editor.job).toBe(job)
      expect(editor.editing).toBe(false)
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(requests('POST /api/batch/derive')).toHaveLength(1)
      expect(documentOf(editor)).toEqual(before)
      expect(editor.canUndo).toBe(true)
    })

    it('a failed derive: the toast, the failure, the shown job back, nothing recorded', async () => {
      server.on('POST /api/batch/derive', () => problem(422, 'request.invalid', 'Bad job'))
      const editor = await edited()
      const before = documentOf(editor)
      const job = editor.job
      editor.set('/video/encoder', 'libx264')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      await flush()
      expect(editor.editFailure).toBe('Bad job')
      expect(editor.job).toBe(job)
      expect(documentOf(editor)).toEqual(before)
      expect(editor.canUndo).toBe(false)
      expect(useToastStore().items.map((toast) => toast.summary)).toEqual(['Bad job'])
    })

    it('the end of a coalescing run during the wait ends the step', async () => {
      const editor = await edited()
      editor.set('/video/rate_control/value', 20, { coalesce: 'quality' })
      editor.endCoalescing()
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      await flush()
      editor.set('/video/rate_control/value', 16, { coalesce: 'quality' })
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      await flush()
      editor.undo()
      expect(documentOf(editor).template.video?.rate_control).toMatchObject({ value: 20 })
    })

    it('an edit on the way stays on screen when an older shown job comes from the server', async () => {
      const editor = await edited()
      const slow = deferred<unknown>()
      let held: Recorded | null = null
      server.on('POST /api/batch/resolve', (request) => {
        held = request
        return slow.promise
      })
      await derivedEdit(editor, [{ op: 'replace', path: '/video/encoder', value: 'libx264' }])
      editor.set('/video/preset', 'veryslow')
      const { template, source_ids } = body<ResolveBody>(held as unknown as Recorded)
      slow.resolve({ columns: [], rows: source_ids.map((id) => row(template, id)), issues: [] })
      await flush()
      expect(editor.job?.video).toMatchObject({ encoder: 'libx264', preset: 'veryslow' })
    })

    it('drops a derive on its way on undo: its answer changes nothing', async () => {
      const slow = deferred<JobTemplate>()
      server.on('POST /api/batch/derive', () => slow.promise)
      const editor = await edited()
      const before = documentOf(editor)
      const job = editor.job
      editor.set('/video/encoder', 'libx264')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(requests('POST /api/batch/derive')).toHaveLength(1)
      editor.undo()
      expect(editor.job).toBe(job)
      slow.resolve(derive(body(requests('POST /api/batch/derive')[0])))
      await flush()
      expect(documentOf(editor)).toEqual(before)
      expect(editor.canUndo).toBe(false)
    })
  })

  describe('an edit of scope file', () => {
    it('goes into the shown file’s override at once, guarded inside a track, one undo step', async () => {
      const editor = await inFile()
      const before = documentOf(editor)
      editor.set('/video/encoder', 'libx264')
      editor.set('/audio/1/bitrate', 320)
      expect(requests('POST /api/batch/derive')).toHaveLength(0)
      expect(documentOf(editor).overrides).toEqual({
        e1: [
          { op: 'replace', path: '/job/video/encoder', value: 'libx264' },
          { op: 'test', path: '/job/audio/1/source_stream', value: 2 },
          { op: 'replace', path: '/job/audio/1/bitrate', value: 320 },
        ],
      })
      expect(documentOf(editor).template).toEqual(before.template)
      expect(editor.job?.audio?.[1]?.bitrate).toBe(320)
      expect(editor.overriddenAt('audio[1].bitrate')).toBe(true)
      expect(editor.overriddenAt('audio[1]')).toBe(true)
      expect(editor.overriddenAt('audio[0].bitrate')).toBe(false)
      await flush()
      expect(body<ResolveBody>(requests('POST /api/batch/resolve-run').at(-1)).overrides).toEqual(
        documentOf(editor).overrides,
      )
      editor.undo()
      expect(documentOf(editor).overrides).toEqual({
        e1: [{ op: 'replace', path: '/job/video/encoder', value: 'libx264' }],
      })
      editor.undo()
      expect(documentOf(editor)).toEqual(before)
    })

    it('shows the job with the override and no override dot in scope group', async () => {
      const editor = await inFile()
      editor.set('/video/encoder', 'libx264')
      await flush()
      expect(body<ResolveBody>(requests('POST /api/batch/resolve').at(-1)).overrides).toEqual({
        e1: [{ op: 'replace', path: '/job/video/encoder', value: 'libx264' }],
      })
      await editor.setScope('group')
      expect(editor.job?.video?.encoder).toBe('libx265')
      expect(editor.overriddenAt('video.encoder')).toBe(false)
    })

    it('refuses adding, removing or moving a track: a toast, nothing changes', async () => {
      const editor = await inFile()
      const before = documentOf(editor)
      const job = editor.job
      editor.patch([{ op: 'remove', path: '/audio/2' }])
      editor.patch([{ op: 'move', from: '/audio/2', path: '/audio/0' }])
      expect(editor.job).toBe(job)
      expect(documentOf(editor)).toEqual(before)
      expect(editor.canUndo).toBe(false)
      expect(useToastStore().items).toHaveLength(2)
    })

    it('Reset to group removes the operations and their guard', async () => {
      const editor = await inFile()
      editor.set('/video/encoder', 'libx264')
      editor.set('/audio/1/bitrate', 320)
      editor.resetToGroup('audio[1]')
      expect(documentOf(editor).overrides).toEqual({
        e1: [{ op: 'replace', path: '/job/video/encoder', value: 'libx264' }],
      })
      editor.resetToGroup('video.encoder')
      expect(documentOf(editor).overrides).toEqual({})
      editor.undo()
      expect(documentOf(editor).overrides.e1).toHaveLength(1)
    })

    it('Apply to whole group puts the value into the template and removes the override, one undo step', async () => {
      const editor = await inFile()
      editor.set('/video/encoder', 'libx264')
      await flush()
      const before = documentOf(editor)
      await editor.applyToWholeGroup('video.encoder')
      await flush()
      const sent = body<{ job: JobSettings; sections: string[] }>(
        requests('POST /api/batch/derive')[0],
      )
      expect(sent.sections).toEqual(['video'])
      expect(sent.job.video?.encoder).toBe('libx264')
      expect(documentOf(editor).template.video?.encoder).toBe('libx264')
      expect(documentOf(editor).overrides).toEqual({})
      editor.undo()
      expect(documentOf(editor)).toEqual(before)
    })

    it('Apply to whole group refuses a per-file field', async () => {
      const editor = await inFile()
      editor.set('/output/path', '/out/mine.mkv')
      const before = documentOf(editor)
      await editor.applyToWholeGroup('output.path')
      expect(documentOf(editor)).toEqual(before)
      expect(requests('POST /api/batch/derive')).toHaveLength(0)
      expect(useToastStore().items.map((toast) => toast.summary)).toEqual([
        'Not applied to the group',
      ])
    })
  })

  describe('matrix actions', () => {
    it('a pick and no track change only that file’s override, one undo step each', async () => {
      const editor = await withRules()
      editor.setNameField('e3', 'episode', '3')
      const before = documentOf(editor)
      editor.pickTrack('e2', 'audio', 0, 3)
      expect(documentOf(editor).overrides).toEqual({
        ...before.overrides,
        e2: [{ op: 'replace', path: '/audio_rules/0/selector/stream', value: 3 }],
      })
      editor.pickTrack('e2', 'audio', 0, null)
      expect(documentOf(editor).overrides.e2).toEqual([
        { op: 'replace', path: '/audio_rules/0/selector/languages', value: [] },
      ])
      expect(documentOf(editor).template).toEqual(before.template)
      editor.resetTrack('e2', 'audio', 0)
      expect(documentOf(editor)).toEqual(before)
      editor.undo()
      editor.undo()
      expect(documentOf(editor).overrides.e2?.[0]).toMatchObject({ value: 3 })
    })

    it('refuses a pick in a column the defaults compile to', async () => {
      const editor = await edited()
      expect(() => editor.pickTrack('e2', 'subtitle', 0, 4)).toThrow(/no explicit subtitle rule/)
      expect(documentOf(editor).overrides).toEqual({})
    })

    it('a name field correction is that file’s, replaced and removed', async () => {
      const editor = await edited()
      editor.setNameField('e2', 'sub_title', 'Pilot')
      editor.setNameField('e2', 'sub_title', 'Departure')
      expect(documentOf(editor).overrides).toEqual({
        e2: [
          { op: 'add', path: '/job/output/naming/field_overrides/sub_title', value: 'Departure' },
        ],
      })
      editor.setNameField('e2', 'sub_title', null)
      expect(documentOf(editor).overrides).toEqual({})
    })

    it('a row fix of target job goes into that file’s override with its guard; template into the template', async () => {
      const editor = await withRules()
      await editor.applyRowFix('e3', {
        label: 'Lower it',
        target: 'job',
        patch: [{ op: 'replace', path: '/audio/0/bitrate', value: 96 }],
      })
      expect(documentOf(editor).overrides).toEqual({
        e3: [
          { op: 'test', path: '/job/audio/0/source_stream', value: 1 },
          { op: 'replace', path: '/job/audio/0/bitrate', value: 96 },
        ],
      })
      await editor.applyRowFix('e3', {
        label: 'Make the rule optional',
        target: 'template',
        patch: [{ op: 'add', path: '/audio_rules/0/required', value: false }],
      })
      expect(documentOf(editor).template.audio_rules?.[0]?.required).toBe(false)
    })

    it('applyFix of target template patches the template', async () => {
      const editor = await withRules()
      await editor.applyFix({
        label: 'Make the rule optional',
        target: 'template',
        patch: [{ op: 'add', path: '/audio_rules/0/required', value: false }],
      })
      expect(documentOf(editor).template.audio_rules?.[0]?.required).toBe(false)
      editor.undo()
      expect(documentOf(editor).template.audio_rules?.[0]).not.toHaveProperty('required')
    })
  })

  describe('presets and merges', () => {
    it('a preset replaces the template in one undo step and keeps the overrides', async () => {
      const editor = await edited()
      editor.setNameField('e2', 'episode', '2')
      const before = documentOf(editor)
      await editor.applyPreset('h264')
      expect(editor.presetId).toBe('h264')
      expect(documentOf(editor).template.video?.encoder).toBe('libx264')
      expect(documentOf(editor).overrides).toEqual(before.overrides)
      editor.undo()
      expect(documentOf(editor)).toEqual(before)
      expect(editor.presetId).toBe(PRESET)
    })

    it('merges into a group never edited: a template from the job’s preset, one step of that group', async () => {
      const editor = useEditorStore()
      await editor.open('other', 'h264')
      const from = {
        ...(editor.job as JobSettings),
        video: { ...editor.job!.video!, preset: 'veryslow' },
      }
      await editor.mergeIntoGroup('g1', from, 'other', ['video'])
      expect(editor.target?.kind).toBe('job')
      expect(body(requests('POST /api/batch/derive')[0])).toMatchObject({
        source_id: 'other',
        sections: ['video'],
      })
      await editor.editGroup('g1')
      expect(editor.presetId).toBe('h264')
      expect(documentOf(editor).template.video?.preset).toBe('veryslow')
      editor.undo()
      expect(documentOf(editor).template).toEqual(templateOfPreset(h264()))
    })
  })

  describe('the matrix', () => {
    it('keeps only the newest answer', async () => {
      const editor = await edited()
      const older = deferred<BatchRun>()
      const answers: (BatchRun | Promise<BatchRun>)[] = []
      server.on('POST /api/batch/resolve-run', (request) => {
        const { template, source_ids } = body<ResolveBody>(request)
        const run: BatchRun = {
          grouping: { groups: [], issues: [] },
          resolutions: [
            { columns: [], rows: source_ids.map((id) => row(template, id)), issues: [] },
          ],
        }
        answers.push(run)
        return answers.length === 1 ? older.promise : run
      })
      editor.patchTemplate([{ op: 'replace', path: '/output/container', value: 'mp4' }])
      await flush()
      editor.patchTemplate([{ op: 'replace', path: '/output/container', value: 'webm' }])
      await flush()
      expect(editor.resolution?.rows?.[0]?.job?.output?.container).toBe('webm')
      older.resolve(answers[0] as BatchRun)
      await flush()
      expect(editor.resolution?.rows?.[0]?.job?.output?.container).toBe('webm')
      expect(editor.resolving).toBe(false)
    })

    it('one request for changes in one turn', async () => {
      const editor = await edited()
      const asked = requests('POST /api/batch/resolve-run').length
      editor.setNameField('e2', 'episode', '2')
      editor.setNameField('e3', 'episode', '3')
      await flush()
      expect(requests('POST /api/batch/resolve-run')).toHaveLength(asked + 1)
    })

    it('resolveNow derives the waiting edits first', async () => {
      const editor = await edited()
      editor.set('/video/encoder', 'libx264')
      const answer = await editor.resolveNow()
      expect(requests('POST /api/batch/derive')).toHaveLength(1)
      expect(answer.rows?.[0]?.job?.video?.encoder).toBe('libx264')
      expect(editor.resolution).toEqual(answer)
    })
  })

  describe('sources', () => {
    it('a member removed: the matrix again without it; the shown file removed: the representative', async () => {
      const editor = await edited()
      await editor.showFile('e3')
      const sources = useSourcesStore()
      sources.entries = sources.entries.filter((entry) => entry.id !== 'e3')
      await flush()
      await flush()
      expect(editor.target?.sourceId).toBe('e1')
      expect(sources.activeId).toBe('e1')
      sources.entries = sources.entries.filter((entry) => entry.id !== 'e2')
      await flush()
      expect(body<ResolveBody>(requests('POST /api/batch/resolve-run').at(-1)).source_ids).toEqual([
        'e1',
      ])
    })

    it('removing the shown file keeps the group open on its representative', async () => {
      server
        .on('DELETE /api/sources/e3', () => new Response(null, { status: 204 }))
        .on('POST /api/batch/group', { groups: [group('g1', ['e1', 'e2'])], issues: [] })
      const sources = useSourcesStore()
      // Probed sources: the panel groups only those.
      sources.entries = sources.entries.map((entry) => ({ ...entry, source: {} as MediaSource }))
      const editor = await edited()
      await editor.showFile('e3')
      await sources.remove('e3')
      await flush()
      expect(editor.target).toMatchObject({ kind: 'group', sourceId: 'e1' })
      expect(useSourcesStore().activeId).toBe('e1')
    })

    it('the group gone: the editor closes', async () => {
      const editor = await edited()
      useSourcesStore().grouping = { groups: [], issues: [] }
      await flush()
      expect(editor.target).toBeNull()
      expect(useSourcesStore().activeId).toBeNull()
    })
  })

  it('validation keeps the template fixes of the shown file’s issues', async () => {
    const fix = { label: 'Make the rule optional', target: 'template' as const, patch: [] }
    server.on('POST /api/batch/resolve', (request) => {
      const { template, source_ids } = body<ResolveBody>(request)
      const issue = {
        severity: 'error',
        code: 'batch.track_missing',
        path: 'audio_rules[1]',
        message: 'x',
        fixes: [fix],
      }
      const rows = source_ids.map((id) => Object.assign(row(template, id), { issues: [issue] }))
      return { columns: [], rows, issues: [] }
    })
    const scope = effectScope()
    scope.run(() => useValidation())
    await edited()
    expect(useValidationStore().issues[0]?.fixes).toEqual([fix])
    scope.stop()
  })

  it('a new shown file or scope is a new session; perFile names the per-file fields', async () => {
    const editor = await edited()
    const session = editor.session
    await editor.showFile('e2')
    await editor.setScope('file')
    expect(editor.session).toBe(session + 2)
    expect(editor.perFile('chapters.names[2]')).toBe(true)
    expect(editor.perFile('audio[0].bitrate')).toBe(false)
  })
})
