import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, reactive } from 'vue'

import { ApiError, configureClient } from '@/api/client'
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

function resolveRun(request: Recorded): BatchRun {
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
      .on('POST /api/batch/resolve-run', resolveRun)
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

    it('derives a merge again when an undo changed the template while it was on its way', async () => {
      const slow = deferred<JobTemplate>()
      const editor = await edited()
      editor.patchTemplate([{ op: 'replace', path: '/output/container', value: 'mp4' }])
      const from = { ...editor.job!, video: { ...editor.job!.video!, preset: 'veryslow' } }
      server.on('POST /api/batch/derive', () => slow.promise)
      const merged = editor.mergeIntoGroup('g1', from, 'e1', ['video'])
      await flush()
      editor.undo()
      server.on('POST /api/batch/derive', (request) => derive(body(request)))
      slow.resolve(derive(body(requests('POST /api/batch/derive')[0])))
      await merged
      expect(requests('POST /api/batch/derive')).toHaveLength(2)
      expect(documentOf(editor).template).toMatchObject({
        output: { container: 'mkv' },
        video: { preset: 'veryslow' },
      })
    })

    it('a template change made while a derive is on its way comes after it', async () => {
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

    it('ends what there was to redo, so a redo does not drop it', async () => {
      const editor = await edited()
      await derivedEdit(editor, [{ op: 'replace', path: '/video/encoder', value: 'libx264' }])
      editor.undo()
      await flush()
      expect(editor.canRedo).toBe(true)
      editor.set('/video/preset', 'veryslow')
      expect(editor.canRedo).toBe(false)
      editor.redo()
      expect(editor.job?.video?.preset).toBe('veryslow')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      await flush()
      expect(documentOf(editor).template.video).toMatchObject({
        encoder: 'libx265',
        preset: 'veryslow',
      })
    })

    it('a template change made while an edit waits comes after that edit’s derive', async () => {
      const editor = await edited()
      const before = documentOf(editor)
      editor.set('/video/encoder', 'libx264')
      const changed = editor.patchTemplate([
        { op: 'replace', path: '/video/preset', value: 'veryfast' },
      ])
      await flush()
      await changed
      expect(documentOf(editor).template.video).toMatchObject({
        encoder: 'libx264',
        preset: 'veryfast',
      })
      editor.undo()
      expect(documentOf(editor).template.video).toMatchObject({
        encoder: 'libx264',
        preset: before.template.video?.preset,
      })
      editor.undo()
      expect(documentOf(editor)).toEqual(before)
    })

    describe('from a near member', () => {
      beforeEach(() => {
        const found = group()
        found.members = found.members?.map((member) =>
          member.path === pathOf('e2') ? { ...member, match: 'near' } : member,
        )
        useSourcesStore().grouping = { groups: [found], issues: [] }
      })

      it('refuses a track edit while the template has no rules of that kind: a toast, nothing changes', async () => {
        const editor = await edited()
        await editor.showFile('e2')
        const before = documentOf(editor)
        const job = editor.job
        editor.set('/audio/0/bitrate', 96)
        editor.set('/subtitles/0/metadata/name', 'Signs')
        await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
        expect(editor.job).toBe(job)
        expect(editor.editing).toBe(false)
        expect(documentOf(editor)).toEqual(before)
        expect(requests('POST /api/batch/derive')).toHaveLength(0)
        const toasts = useToastStore().items
        expect(toasts.map((toast) => toast.summary)).toEqual([
          "E02's tracks do not match the group's",
          "E02's tracks do not match the group's",
        ])
        expect(toasts[0]?.detail).toContain('Show E01')
        // Not a track: derived as from any member.
        await derivedEdit(editor, [{ op: 'replace', path: '/video/encoder', value: 'libx264' }])
        expect(documentOf(editor).template.video?.encoder).toBe('libx264')
      })

      it('takes a track edit of a kind the template has rules for', async () => {
        const editor = await withRules()
        await editor.showFile('e2')
        await derivedEdit(editor, [{ op: 'replace', path: '/audio/0/bitrate', value: 96 }])
        expect(body(requests('POST /api/batch/derive')[0])).toMatchObject({
          source_id: 'e2',
          sections: ['audio'],
        })
        editor.set('/subtitles/0/metadata/name', 'Signs')
        expect(useToastStore().items).toHaveLength(1)
      })

      it('Apply to whole group refuses a track value of a kind the template has no rules for', async () => {
        const editor = await edited()
        await editor.showFile('e2')
        await editor.setScope('file')
        editor.set('/audio/0/bitrate', 96)
        const before = documentOf(editor)
        await editor.applyToWholeGroup('audio[0].bitrate')
        expect(documentOf(editor)).toEqual(before)
        expect(requests('POST /api/batch/derive')).toHaveLength(0)
        expect(useToastStore().items.map((toast) => toast.summary)).toEqual([
          "E02's tracks do not match the group's",
        ])
      })
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
          { op: 'test', path: '/job/audio/1', value: sampleJob().audio?.[1] },
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
      const guard = {
        op: 'test',
        path: '/audio_rules/0/selector',
        value: { kind: 'audio', languages: ['ja'] },
      }
      editor.pickTrack('e2', 'audio', 0, 3)
      expect(documentOf(editor).overrides).toEqual({
        ...before.overrides,
        e2: [guard, { op: 'replace', path: '/audio_rules/0/selector/stream', value: 3 }],
      })
      editor.pickTrack('e2', 'audio', 0, null)
      expect(documentOf(editor).overrides.e2).toEqual([
        guard,
        { op: 'replace', path: '/audio_rules/0/selector/languages', value: [] },
      ])
      expect(documentOf(editor).template).toEqual(before.template)
      editor.resetTrack('e2', 'audio', 0)
      expect(documentOf(editor)).toEqual(before)
      editor.undo()
      editor.undo()
      expect(documentOf(editor).overrides.e2?.[1]).toMatchObject({ value: 3 })
    })

    it('guards a pick with the rule’s selector as the template has it now', async () => {
      const editor = await withRules()
      editor.pickTrack('e2', 'audio', 0, 3)
      await editor.patchTemplate([
        { op: 'replace', path: '/audio_rules/0/selector/languages', value: ['en'] },
      ])
      editor.pickTrack('e2', 'audio', 0, 2)
      expect(documentOf(editor).overrides.e2).toEqual([
        {
          op: 'test',
          path: '/audio_rules/0/selector',
          value: { kind: 'audio', languages: ['en'] },
        },
        { op: 'replace', path: '/audio_rules/0/selector/stream', value: 2 },
      ])
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
          { op: 'test', path: '/job/audio/0', value: sampleJob().audio?.[0] },
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

    it('a preset with the group’s template only becomes the group’s preset: no undo step', async () => {
      server.on('GET /api/presets/saved', { ...samplePreset(), id: 'saved', name: 'Saved' })
      const editor = await edited()
      const before = documentOf(editor)
      await editor.applyPreset('saved')
      expect(editor.presetId).toBe('saved')
      expect(documentOf(editor)).toEqual(before)
      expect(editor.canUndo).toBe(false)
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

    it('resolveNow waits for a field’s pending edit and the derive it leads to', async () => {
      const editor = await edited()
      const edit = reactive({
        failure: null,
        flush() {
          setTimeout(() => {
            editor.set('/video/encoder', 'libx264')
            editor.endEdit(edit)
          }, 100)
        },
      })
      editor.beginEdit(edit)
      const answer = editor.resolveNow()
      await vi.advanceTimersByTimeAsync(100)
      await flush()
      expect((await answer).rows?.[0]?.job?.video?.encoder).toBe('libx264')
      expect(requests('POST /api/batch/derive')).toHaveLength(1)
    })

    it('resolveNow rejects when a field’s edit fails, and resolves nothing', async () => {
      const editor = await edited()
      const asked = requests('POST /api/batch/resolve-run').length
      const edit = reactive({
        failure: null as string | null,
        flush() {
          edit.failure = 'The preview failed'
        },
      })
      editor.beginEdit(edit)
      await expect(editor.resolveNow()).rejects.toMatchObject({
        problem: { detail: 'The preview failed' },
      })
      expect(requests('POST /api/batch/resolve-run')).toHaveLength(asked)
    })

    it('a failed resolve keeps the last matrix and says why, without a toast; a retry asks again', async () => {
      const editor = await edited()
      const last = editor.resolution
      server.on('POST /api/batch/resolve-run', () =>
        problem(422, 'request.invalid', 'Bad request', 'The template is not valid'),
      )
      editor.setNameField('e2', 'episode', '2')
      await flush()
      expect(editor.matrixError).toBe('The template is not valid')
      expect(editor.resolution).toBe(last)
      expect(editor.resolving).toBe(false)
      expect(useToastStore().items).toEqual([])

      server.on('POST /api/batch/resolve-run', resolveRun)
      const asked = requests('POST /api/batch/resolve-run').length
      editor.retryMatrix()
      await flush()
      expect(requests('POST /api/batch/resolve-run')).toHaveLength(asked + 1)
      expect(editor.matrixError).toBeNull()
      expect(editor.resolution?.rows?.[1]?.override).toHaveLength(1)
    })

    it('a failed resolveNow rejects with the ApiError, sets matrixError (a stale source in words), and shows no toast', async () => {
      const editor = await edited()
      server.on('POST /api/batch/resolve-run', () =>
        problem(409, 'source.stale', 'Source changed', 'Probe it again with POST /api/sources.'),
      )
      await expect(editor.resolveNow()).rejects.toBeInstanceOf(ApiError)
      expect(editor.matrixError).toBe(
        'A file of the group changed on disk since it was opened: remove it from the sources and open it again.',
      )
      expect(useToastStore().items).toEqual([])
    })

    it('has no error once the group is left', async () => {
      const editor = await edited()
      server.on('POST /api/batch/resolve-run', () => problem(500, 'internal', 'Broken'))
      editor.setNameField('e2', 'episode', '2')
      await flush()
      expect(editor.matrixError).toBe('Broken')
      await editor.open('other')
      expect(editor.matrixError).toBeNull()
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

    it('a new id for the edited group (an earlier episode opened): its state follows', async () => {
      const editor = await edited()
      await derivedEdit(editor, [{ op: 'replace', path: '/video/encoder', value: 'libx264' }])
      const before = documentOf(editor)
      const sources = useSourcesStore()
      sources.entries = [{ id: 'e0', path: pathOf('e0'), source: null }, ...sources.entries]
      sources.grouping = { groups: [group('g0', ['e0', ...IDS])], issues: [] }
      await flush()
      expect(editor.target).toMatchObject({ kind: 'group', groupId: 'g0', sourceId: 'e1' })
      expect(editor.group?.id).toBe('g0')
      expect(documentOf(editor)).toEqual(before)
      expect(editor.canUndo).toBe(true)
      expect(body<ResolveBody>(requests('POST /api/batch/resolve-run').at(-1)).source_ids).toEqual([
        'e0',
        ...IDS,
      ])
      await editor.editGroup('g0')
      expect(editor.canUndo).toBe(true)
    })

    it('a kept state follows most of its members when its representative left', async () => {
      const sources = useSourcesStore()
      sources.entries = [...sources.entries, { id: 'e4', path: pathOf('e4'), source: null }]
      sources.grouping = { groups: [group('g1', [...IDS, 'e4'])], issues: [] }
      const editor = await edited()
      editor.setNameField('e3', 'episode', '3')
      const before = documentOf(editor)
      await editor.open('other')
      sources.grouping = {
        groups: [group('ga', ['e2', 'other']), group('gb', ['e3', 'e4'])],
        issues: [],
      }
      await editor.editGroup('gb')
      expect(documentOf(editor)).toEqual(before)
      await editor.editGroup('ga')
      expect(documentOf(editor).overrides).toEqual({})
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

  it('amends nothing in a group: its files detect their own crop', async () => {
    const editor = await edited()
    const before = documentOf(editor)
    const shown = JSON.stringify(editor.job)
    editor.amend([
      {
        op: 'replace',
        path: '/dimensions/crop/rect',
        value: { top: 2, bottom: 2, left: 0, right: 0 },
      },
    ])
    expect(documentOf(editor)).toEqual(before)
    expect(JSON.stringify(editor.job)).toBe(shown)
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
