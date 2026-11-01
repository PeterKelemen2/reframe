import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import { ApiError, configureClient } from '@/api/client'
import { deferred, FakeServer, problem, type Recorded } from '@/api/testing/fakes'
import type { FieldChange, Fix, JobDraft, JobSettings, JsonPatchOp, SourceEntry } from '@/api/types'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'

import { EDIT_DEBOUNCE, PatchError, useEditorStore } from './editor'
import { usePresetsStore } from './presets'
import { useSourcesStore } from './sources'
import { useToastStore } from './toasts'

const DEFAULT_PRESET = 'h265-mkv-1080p'

/** The job the fake server drafts for a source and a preset. */
function draftFor(sourceId: string, presetId: string | null): JobDraft {
  const job = sampleJob()
  job.source.path = `/media/${sourceId}.mkv`
  job.preset_id = presetId ?? DEFAULT_PRESET
  if (job.preset_id !== DEFAULT_PRESET) job.video!.encoder = 'libx264'
  return sampleDraft(job)
}

function presetNamed(id: string) {
  return { ...samplePreset(), id, name: id }
}

/** Lets the fake answers and the zero-delay timers run. */
async function flush(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0)
}

function body(request: Recorded | undefined): Record<string, unknown> {
  return request?.body as Record<string, unknown>
}

async function opened(sourceId = 'movie') {
  const editor = useEditorStore()
  await editor.open(sourceId)
  await flush()
  return editor
}

function fix(patch: JsonPatchOp[], target: Fix['target'] = 'job'): Fix {
  return { label: 'Use hevc_amf (closest match)', patch, target }
}

function sourceEntry(id: string): SourceEntry {
  return { id, path: '/media/queued.mkv', source: null }
}

function changed(path: string): FieldChange {
  return { path, kind: 'changed' }
}

function pendingEdit(failure: string | null = null) {
  return reactive({ flush: vi.fn<() => void>(), failure })
}

/** Runs `each` for one item after the other: edits that must come in turn. */
async function inTurn<T>(items: readonly T[], each: (item: T) => Promise<void>): Promise<void> {
  const [first, ...rest] = items
  if (first === undefined) return
  await each(first)
  await inTurn(rest, each)
}

describe('the editor store', () => {
  let server: FakeServer

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    server = new FakeServer()
      .on('POST /api/jobs/draft', (request) => {
        const { source_id, preset_id } = body(request) as { source_id: string; preset_id: string }
        return draftFor(source_id, preset_id)
      })
      .on('POST /api/presets/diff', [])
      .on(`GET /api/presets/${DEFAULT_PRESET}`, presetNamed(DEFAULT_PRESET))
      .on('GET /api/presets/h264', presetNamed('h264'))
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function requests(route: string): Recorded[] {
    return server.requests.filter((request) => `${request.method} ${request.path}` === route)
  }

  describe('open', () => {
    it('drafts the source with the default preset and starts a new history', async () => {
      usePresetsStore().defaultId = 'h264'
      const editor = await opened('first')
      editor.set('/video/preset', 'medium')
      await editor.open('second')

      expect(body(requests('POST /api/jobs/draft').at(-1))).toEqual({
        source_id: 'second',
        preset_id: 'h264',
      })
      expect(editor.target).toMatchObject({ kind: 'job', sourceId: 'second' })
      expect(editor.job?.source.path).toBe('/media/second.mkv')
      expect(editor.draft?.job).toBe(editor.job)
      expect(editor.presetId).toBe('h264')
      expect(editor.canUndo).toBe(false)
    })

    it("sends the preset it is given, and null for the server's default", async () => {
      const editor = useEditorStore()
      await editor.open('movie', 'h264')
      await editor.open('movie', null)
      expect(requests('POST /api/jobs/draft').map((request) => body(request).preset_id)).toEqual([
        'h264',
        null,
      ])
    })

    it('keeps the answer of the newest open when an older one comes later', async () => {
      const slow = deferred<JobDraft>()
      server.on('POST /api/jobs/draft', (request) => {
        const { source_id } = body(request) as { source_id: string }
        return source_id === 'first' ? slow.promise : draftFor(source_id, null)
      })
      const editor = useEditorStore()
      const first = editor.open('first')
      await editor.open('second')
      expect(editor.loading).toBe(false)
      slow.resolve(draftFor('first', null))
      await first
      expect(editor.target).toMatchObject({ sourceId: 'second' })
    })

    it('is loading until the draft comes', async () => {
      const slow = deferred<JobDraft>()
      server.on('POST /api/jobs/draft', () => slow.promise)
      const editor = useEditorStore()
      const opening = editor.open('movie')
      await flush()
      expect(editor.loading).toBe(true)
      slow.resolve(draftFor('movie', null))
      await opening
      expect(editor.loading).toBe(false)
    })

    it('rejects a failed draft, which is a toast, and keeps the open job', async () => {
      const editor = await opened('first')
      const job = editor.job
      server.on('POST /api/jobs/draft', () => problem(404, 'sources.unknown', 'No source x'))
      await expect(editor.open('x')).rejects.toBeInstanceOf(ApiError)
      expect(editor.job).toBe(job)
      expect(editor.loading).toBe(false)
      expect(useToastStore().items.map((toast) => toast.summary)).toEqual(['No source x'])
    })
  })

  describe('patches, undo and redo', () => {
    const cases: [string, JsonPatchOp[]][] = [
      ['add a member', [{ op: 'add', path: '/video/advanced/rc-lookahead', value: 40 }]],
      ['add a list item', [{ op: 'add', path: '/audio/1', value: { ...sampleJob().audio?.[0] } }]],
      ['add at the end', [{ op: 'add', path: '/subtitles/-', value: sampleJob().subtitles?.[0] }]],
      ['remove a member', [{ op: 'remove', path: '/filters/interlace_detection' }]],
      ['remove a list item', [{ op: 'remove', path: '/audio/0' }]],
      ['replace a value', [{ op: 'replace', path: '/video/rate_control/value', value: 18 }]],
      [
        'replace an object',
        [
          {
            op: 'replace',
            path: '/video/rate_control',
            value: { mode: 'bitrate', kbps: 6000, two_pass: true },
          },
        ],
      ],
      ['move a list item', [{ op: 'move', from: '/audio/2', path: '/audio/0' }]],
      ['copy a list item', [{ op: 'copy', from: '/audio/1', path: '/audio/3' }]],
      [
        'test, then replace',
        [
          { op: 'test', path: '/video/encoder', value: 'libx265' },
          { op: 'replace', path: '/video/encoder', value: 'libsvtav1' },
        ],
      ],
      [
        'several kinds at once',
        [
          { op: 'remove', path: '/filters/deinterlace' },
          {
            op: 'add',
            path: '/filters/deinterlace',
            value: { preset: 'bob', tune: null, custom: null, implementation: null },
          },
          { op: 'move', from: '/subtitles/0', path: '/subtitles/0' },
        ],
      ],
    ]

    it.each(cases)('undoes and redoes "%s" to the exact job', async (_name, ops) => {
      const editor = await opened()
      const before = JSON.stringify(editor.job)
      editor.patch(ops)
      const after = JSON.stringify(editor.job)
      expect(after).not.toBe(before)

      editor.undo()
      expect(JSON.stringify(editor.job)).toBe(before)
      expect(editor.canUndo).toBe(false)
      expect(editor.canRedo).toBe(true)
      editor.redo()
      expect(JSON.stringify(editor.job)).toBe(after)
      expect(editor.canRedo).toBe(false)
    })

    it('makes a slider drag with one coalescing key one undo step', async () => {
      const editor = await opened()
      for (let value = 21; value >= 14; value -= 1) {
        editor.set('/video/rate_control/value', value, { coalesce: 'video.rate_control.value' })
      }
      editor.set('/video/preset', 'medium', { coalesce: 'video.preset' })
      editor.undo()
      expect(editor.get('/video/rate_control/value')).toBe(14)
      editor.undo()
      expect(editor.get('/video/rate_control/value')).toBe(22)
      expect(editor.canUndo).toBe(false)
    })

    it('starts a new step with the same key after endCoalescing', async () => {
      const editor = await opened()
      editor.set('/video/rate_control/value', 20, { coalesce: 'quality' })
      editor.endCoalescing()
      editor.set('/video/rate_control/value', 18, { coalesce: 'quality' })
      editor.undo()
      expect(editor.get('/video/rate_control/value')).toBe(20)
    })

    it('ends a run with an undo: the next patch with its key is a step of its own', async () => {
      const editor = await opened()
      editor.set('/video/rate_control/value', 20, { coalesce: 'quality' })
      editor.set('/video/preset', 'fast')
      editor.undo()
      editor.set('/video/rate_control/value', 18, { coalesce: 'quality' })
      editor.undo()
      expect(editor.get('/video/rate_control/value')).toBe(20)
    })

    it('changes nothing for a patch that does not apply', async () => {
      const editor = await opened()
      const job = editor.job
      expect(() =>
        editor.patch([
          { op: 'replace', path: '/video/encoder', value: 'libx264' },
          { op: 'remove', path: '/video/missing' },
        ]),
      ).toThrow(PatchError)
      expect(editor.job).toBe(job)
      expect(editor.canUndo).toBe(false)
    })

    it('refuses a patch while no job is open', () => {
      expect(() => useEditorStore().set('/video/encoder', 'libx264')).toThrow(/no job is open/)
    })

    it('replaces a member, adds a missing one and appends to a list', async () => {
      const editor = await opened()
      editor.set('/video/tune', 'grain')
      editor.set('/video/advanced/rc-lookahead', 40)
      editor.set('/audio/3', { ...(editor.get('/audio/0') as object), source_stream: 9 })
      expect(editor.get('/video/tune')).toBe('grain')
      expect(editor.get('/video/advanced/rc-lookahead')).toBe(40)
      expect(editor.get('/audio/3/source_stream')).toBe(9)
      expect(editor.job?.audio).toHaveLength(4)
    })

    it('keeps the job and the steps to redo for a patch that changes nothing', async () => {
      const editor = await opened()
      editor.set('/video/preset', 'fast')
      editor.undo()
      const job = editor.job
      editor.set('/video/preset', 'slow')
      expect(editor.job).toBe(job)
      expect(editor.canRedo).toBe(true)
    })

    it('hands out a frozen job, so a change can only be a patch', async () => {
      const editor = await opened()
      expect(() => {
        ;(editor.job!.video as { encoder: string }).encoder = 'libx264'
      }).toThrow(TypeError)
    })

    it('clears a history that no longer fits the job, and leaves the job alone', async () => {
      const editor = await opened()
      editor.patch([{ op: 'remove', path: '/filters/deinterlace' }])
      const job = sampleJob()
      delete job.filters
      editor.target = { kind: 'job', sourceId: 'movie', job }
      vi.spyOn(console, 'error').mockImplementation(() => {})
      editor.undo()
      expect(editor.job).toBe(job)
      expect(editor.canUndo).toBe(false)
    })
  })

  describe('applyFix', () => {
    it("applies a job fix's patch as one undo step", async () => {
      const editor = await opened()
      const before = JSON.stringify(editor.job)
      await editor.applyFix(
        fix([
          { op: 'replace', path: '/video/encoder', value: 'hevc_amf' },
          { op: 'replace', path: '/video/rate_control/value', value: 20 },
          { op: 'replace', path: '/video/preset', value: null },
        ]),
      )
      expect(editor.get('/video/encoder')).toBe('hevc_amf')
      editor.undo()
      expect(JSON.stringify(editor.job)).toBe(before)
      expect(editor.canUndo).toBe(false)
    })

    it('shows a toast for a fix that no longer applies and changes nothing', async () => {
      const editor = await opened()
      const job = editor.job
      await editor.applyFix(fix([{ op: 'replace', path: '/audio/7/bitrate', value: 128 }]))
      expect(editor.job).toBe(job)
      expect(useToastStore().items).toMatchObject([
        { severity: 'error', summary: 'The fix could not be applied' },
      ])
    })

    it('sends a settings fix to the server settings and leaves the job alone', async () => {
      server.on('PUT /api/settings', {
        settings: { schema_version: 1 },
        changes: [],
        saved: true,
        warnings: [],
      })
      const editor = await opened()
      const job = editor.job
      const patch: JsonPatchOp[] = [
        { op: 'replace', path: '/output/collision', value: 'overwrite' },
      ]
      await editor.applyFix(fix(patch, 'settings'))
      expect(requests('PUT /api/settings').map((request) => request.body)).toEqual([patch])
      expect(editor.job).toBe(job)
      expect(editor.canUndo).toBe(false)
    })

    it('shows the problem of a refused settings fix as a toast', async () => {
      server.on('PUT /api/settings', () =>
        problem(422, 'settings.invalid', 'Not allowed', 'The folder is outside the output roots.'),
      )
      const editor = await opened()
      await editor.applyFix(
        fix([{ op: 'replace', path: '/output/naming/output_folder', value: '/x' }], 'settings'),
      )
      expect(useToastStore().items).toMatchObject([
        {
          summary: 'The fix could not be applied',
          detail: 'The folder is outside the output roots.',
        },
      ])
    })

    it('refuses a template fix while a job is open', async () => {
      const editor = await opened()
      await expect(editor.applyFix(fix([], 'template'))).rejects.toThrow(/group/)
    })
  })

  describe('applyPreset', () => {
    it('drafts again as one undo step; undo brings back the job, its preset and its draft', async () => {
      const editor = await opened()
      editor.set('/video/rate_control/value', 19)
      const edited = JSON.stringify(editor.job)
      const firstDraft = editor.draft
      await editor.applyPreset('h264')

      expect(body(requests('POST /api/jobs/draft').at(-1))).toEqual({
        source_id: 'movie',
        preset_id: 'h264',
      })
      expect(editor.presetId).toBe('h264')
      expect(editor.get('/video/encoder')).toBe('libx264')
      const secondDraft = editor.draft
      expect(secondDraft?.job).toBe(editor.job)

      editor.undo()
      expect(JSON.stringify(editor.job)).toBe(edited)
      expect(editor.presetId).toBe(DEFAULT_PRESET)
      expect(editor.draft).toBe(firstDraft)
      editor.redo()
      expect(editor.presetId).toBe('h264')
      expect(editor.draft).toBe(secondDraft)
      editor.undo()
      editor.undo()
      expect(editor.get('/video/rate_control/value')).toBe(22)
    })

    it('keeps an edit made while the preset loads in the step it undoes to', async () => {
      const slow = deferred<JobDraft>()
      const editor = await opened()
      server.on('POST /api/jobs/draft', () => slow.promise)
      const applying = editor.applyPreset('h264')
      editor.set('/video/preset', 'fast')
      slow.resolve(draftFor('movie', 'h264'))
      await applying
      editor.undo()
      expect(editor.get('/video/preset')).toBe('fast')
    })

    it('drops its answer when another source was opened meanwhile', async () => {
      const slow = deferred<JobDraft>()
      const editor = await opened('first')
      server.on('POST /api/jobs/draft', (request) =>
        body(request).preset_id === 'h264' ? slow.promise : draftFor('second', null),
      )
      const applying = editor.applyPreset('h264')
      await editor.open('second')
      slow.resolve(draftFor('first', 'h264'))
      await applying
      expect(editor.target).toMatchObject({ sourceId: 'second' })
      expect(editor.presetId).toBe(DEFAULT_PRESET)
    })

    it('rejects without an open job', async () => {
      await expect(useEditorStore().applyPreset('h264')).rejects.toThrow(/no job is open/)
    })
  })

  describe('loadJob', () => {
    it("opens the job's source and edits the job with a new history and no draft", async () => {
      const editor = await opened()
      editor.set('/video/preset', 'fast')
      const sources = useSourcesStore()
      const ensure = vi.spyOn(sources, 'ensure').mockResolvedValue(sourceEntry('queued'))
      const queued: JobSettings = { ...sampleJob(), source: { path: '/media/queued.mkv' } }
      await editor.loadJob(queued)

      expect(ensure).toHaveBeenCalledExactlyOnceWith('/media/queued.mkv')
      expect(editor.target).toMatchObject({ kind: 'job', sourceId: 'queued' })
      expect(editor.job).toEqual(queued)
      expect(editor.job).not.toBe(queued)
      expect(Object.isFrozen(editor.job)).toBe(true)
      expect(editor.draft).toBeNull()
      expect(editor.canUndo).toBe(false)
      expect(sources.activeId).toBe('queued')
    })

    it('rejects when the source cannot be opened and keeps the editor as it was', async () => {
      const editor = await opened()
      const job = editor.job
      vi.spyOn(useSourcesStore(), 'ensure').mockRejectedValue(new Error('probe failed'))
      await expect(editor.loadJob(sampleJob())).rejects.toThrow('probe failed')
      expect(editor.job).toBe(job)
      expect(editor.loading).toBe(false)
    })
  })

  it('closes: no job, draft, history or preset changes, and a draft on its way is dropped', async () => {
    server.on('POST /api/presets/diff', [{ path: 'video.encoder', kind: 'changed' }])
    const editor = await opened()
    editor.set('/video/preset', 'fast')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(editor.modified).toBe(true)
    const slow = deferred<JobDraft>()
    server.on('POST /api/jobs/draft', () => slow.promise)
    const opening = editor.open('other')
    editor.close()
    slow.resolve(draftFor('other', null))
    await opening
    await flush()
    expect(editor.target).toBeNull()
    expect(editor.draft).toBeNull()
    expect(editor.canUndo).toBe(false)
    expect(editor.modified).toBe(false)
    expect(editor.loading).toBe(false)
  })

  it('closes and still takes a draft on its way with keepLoading (another source being opened)', async () => {
    const editor = await opened()
    const slow = deferred<JobDraft>()
    server.on('POST /api/jobs/draft', () => slow.promise)
    const opening = editor.open('other')
    editor.close({ keepLoading: true })
    expect(editor.job).toBeNull()
    expect(editor.loading).toBe(true)
    slow.resolve(draftFor('other', null))
    await opening
    await flush()
    expect(editor.job?.source.path).toBe('/media/other.mkv')
    expect(editor.loading).toBe(false)
  })

  describe('pending edits', () => {
    it('says an edit is on its way until it ends, and a failed one apart', async () => {
      const editor = await opened()
      const naming = pendingEdit()
      const other = pendingEdit()
      editor.beginEdit(naming)
      editor.beginEdit(other)
      editor.beginEdit(naming)
      expect(editor.editing).toBe(true)
      editor.endEdit(naming)
      expect(editor.editing).toBe(true)

      other.failure = 'The server did not answer.'
      expect(editor.editing).toBe(false)
      expect(editor.editFailure).toBe('The server did not answer.')
      editor.endEdit(other)
      expect(editor.editFailure).toBeNull()
    })

    it('asks each pending edit to come in at once', async () => {
      const editor = await opened()
      const first = pendingEdit()
      const failed = pendingEdit('broken')
      editor.beginEdit(first)
      editor.beginEdit(failed)
      editor.flushEdits()
      expect(first.flush).toHaveBeenCalledTimes(1)
      expect(failed.flush).toHaveBeenCalledTimes(1)
    })

    it('forgets the edits of the last job when another job is opened', async () => {
      const editor = await opened()
      editor.beginEdit(pendingEdit())
      await editor.open('other')
      expect(editor.editing).toBe(false)
    })
  })

  describe('presetChanges', () => {
    it('diffs the template against the preset at once after open', async () => {
      server.on('POST /api/presets/diff', [changed('video.encoder')])
      const editor = await opened()
      expect(requests('POST /api/presets/diff')).toHaveLength(1)
      expect(body(requests('POST /api/presets/diff')[0])).toEqual({
        template: JSON.parse(JSON.stringify(editor.currentTemplate)),
        preset_id: DEFAULT_PRESET,
      })
      expect(editor.presetChanges).toEqual([changed('video.encoder')])
      expect(editor.modified).toBe(true)
    })

    it('diffs once, 250 ms after the last of several edits', async () => {
      const editor = await opened()
      await inTurn([21, 20, 19, 18, 17], async (value) => {
        editor.set('/video/rate_control/value', value, { coalesce: 'quality' })
        await vi.advanceTimersByTimeAsync(100)
      })
      expect(requests('POST /api/presets/diff')).toHaveLength(1)
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 100 - 1)
      expect(requests('POST /api/presets/diff')).toHaveLength(1)
      server.on('POST /api/presets/diff', [changed('video.rate_control.value')])
      await vi.advanceTimersByTimeAsync(1)
      expect(requests('POST /api/presets/diff')).toHaveLength(2)
      expect(body(requests('POST /api/presets/diff')[1])).toMatchObject({
        template: { video: { rate_control: { value: 17 } } },
      })
      expect(editor.presetChanges).toEqual([changed('video.rate_control.value')])
    })

    it("sends nothing for an edit of the job's own parts", async () => {
      const editor = await opened()
      editor.set('/audio/0/bitrate', 128)
      editor.set('/output/path', '/output/other.mkv')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE * 2)
      expect(requests('POST /api/presets/diff')).toHaveLength(1)
    })

    it('never takes an older answer over a newer one', async () => {
      const editor = await opened()
      const older = deferred<FieldChange[]>()
      server.on('POST /api/presets/diff', () => older.promise)
      editor.set('/video/preset', 'fast')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      server.on('POST /api/presets/diff', [changed('video.preset'), changed('video.tune')])
      editor.set('/video/tune', 'grain')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      older.resolve([changed('video.preset')])
      await flush()
      expect(editor.presetChanges).toEqual([changed('video.preset'), changed('video.tune')])
    })

    it('follows the new preset after applyPreset, and the old one after its undo', async () => {
      server.on('POST /api/presets/diff', (request) =>
        body(request).preset_id === 'h264' ? [] : [changed('video.preset')],
      )
      const editor = await opened()
      editor.set('/video/preset', 'fast')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(editor.modified).toBe(true)

      await editor.applyPreset('h264')
      expect(editor.presetChanges).toEqual([])
      await flush()
      expect(body(requests('POST /api/presets/diff').at(-1)).preset_id).toBe('h264')
      expect(editor.modified).toBe(false)

      editor.undo()
      await flush()
      expect(body(requests('POST /api/presets/diff').at(-1)).preset_id).toBe(DEFAULT_PRESET)
      expect(editor.presetChanges).toEqual([changed('video.preset')])
    })

    it('reads the preset once when the presets store does not have it, and not when it does', async () => {
      await opened()
      expect(requests(`GET /api/presets/${DEFAULT_PRESET}`)).toHaveLength(1)

      setActivePinia(createPinia())
      usePresetsStore().presets = [presetNamed(DEFAULT_PRESET)]
      await opened()
      expect(requests(`GET /api/presets/${DEFAULT_PRESET}`)).toHaveLength(1)
      expect(useEditorStore().currentTemplate).not.toBeNull()
    })

    it('drops the changes and the diff on its way when the preset is gone', async () => {
      usePresetsStore().presets = [presetNamed(DEFAULT_PRESET)]
      server.on('POST /api/presets/diff', [changed('video.preset')])
      const editor = await opened()
      expect(editor.modified).toBe(true)
      editor.set('/video/preset', 'fast')
      usePresetsStore().presets = []
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(editor.currentTemplate).toBeNull()
      expect(editor.modified).toBe(false)
      expect(requests('POST /api/presets/diff')).toHaveLength(1)
    })

    it('clears the changes when the diff says the preset is gone', async () => {
      server.on('POST /api/presets/diff', [changed('video.preset')])
      const editor = await opened()
      server.on('POST /api/presets/diff', () => problem(404, 'preset.not_found', 'No preset'))
      editor.set('/video/preset', 'fast')
      await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
      expect(editor.presetChanges).toEqual([])
    })

    it('asks again at once on refreshPresetChanges', async () => {
      const editor = await opened()
      server.on('POST /api/presets/diff', [changed('video.preset')])
      editor.refreshPresetChanges()
      await flush()
      expect(editor.presetChanges).toEqual([changed('video.preset')])
    })
  })
})
