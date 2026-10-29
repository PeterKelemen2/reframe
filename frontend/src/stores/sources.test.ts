import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, configureClient } from '@/api/client'
import { deferred, FakeServer, problem, type Recorded, settle } from '@/api/testing/fakes'
import type { MediaSource, Schemas, SourceEntry, TaskInfo } from '@/api/types'
import { platform } from '@/platform'

import { useEditorStore } from './editor'
import { GROUP_LEVEL, SourceOpenError, useSourcesStore } from './sources'
import { TaskLostError, useTasksStore } from './tasks'
import { useToastStore } from './toasts'

function source(path: string, warnings: string[] = []): MediaSource {
  return {
    schema_version: 1,
    ref: { path },
    container: { display_name: 'MKV', duration: 4 },
    video: [],
    warnings,
  }
}

const idOf = (path: string) => `src-${path.split('/').at(-1)}`

// Unique across the tests: a timer of an earlier test must not end a task of a later one.
let tasksStarted = 0

interface Probe {
  request: Recorded
  taskId: string
}

/**
 * A server with media files and folders. `POST /api/sources` starts a task the test ends with
 * `done`, `fail` or `lose`; `auto` ends each one at once with what the files give.
 */
class MediaServer extends FakeServer {
  files = new Map<string, MediaSource | null>()
  folders = new Map<string, string[]>()
  /** `GET /api/sources`: what this server probed (other clients' sources too). */
  registry: SourceEntry[] = []
  probes: Probe[] = []
  auto = true
  groupings: Schemas['BatchGrouping'][] = []

  constructor() {
    super()
    this.on('POST /api/sources', (request) => {
      const probe = { request, taskId: `t${++tasksStarted}` }
      this.probes.push(probe)
      if (this.auto) setTimeout(() => this.done(probe), 0)
      return { task_id: probe.taskId }
    })
      .on('GET /api/sources', () => this.registry)
      .on('POST /api/batch/group', () => this.groupings.shift() ?? { groups: [], issues: [] })
  }

  add(path: string, media: MediaSource | null = source(path)): this {
    this.files.set(path, media)
    this.on(`DELETE /api/sources/${idOf(path)}`, () => new Response(null, { status: 204 }))
    return this
  }

  /** The task's result: each file of the paths that has a source, the others as errors. */
  summary(paths: string[]) {
    const files = paths.flatMap((path) => this.folders.get(path) ?? [path])
    const sources = files
      .filter((file) => this.files.get(file))
      .map((file) => ({ id: idOf(file), path: file }))
    const errors = files
      .filter((file) => !this.files.get(file))
      .map((file) => ({ path: file, code: 'probe.not_found', message: 'The file does not exist.' }))
    for (const { id, path } of sources) {
      this.registry = this.registry.filter((entry) => entry.id !== id)
      this.registry.push({ id, path, source: this.files.get(path) ?? null })
    }
    return { sources, errors }
  }

  done(probe: Probe, result?: unknown): void {
    const { paths } = probe.request.body as { paths: string[] }
    useTasksStore().onTaskDone({
      type: 'task.done',
      task: {
        id: probe.taskId,
        kind: 'probe_sources',
        state: 'done',
        result: (result ?? this.summary(paths)) as never,
      },
    })
  }

  progress(probe: Probe, task: Partial<TaskInfo>): void {
    useTasksStore().onTaskProgress({
      type: 'task.progress',
      task: { id: probe.taskId, kind: 'probe_sources', state: 'running', ...task },
    })
  }

  end(probe: Probe, task: Partial<TaskInfo>): void {
    useTasksStore().onTaskDone({
      type: 'task.done',
      task: { id: probe.taskId, kind: 'probe_sources', state: 'failed', ...task },
    })
  }

  last(): Probe {
    const probe = this.probes.at(-1)
    if (probe === undefined) throw new Error('no probe yet')
    return probe
  }
}

function group(
  name: string,
  members: { path: string; match?: 'exact' | 'near'; differences?: string[] }[],
): Schemas['BatchGroup'] {
  return {
    id: `g:${name}`,
    name,
    level: 'standard',
    representative: members[0]?.path ?? '',
    fingerprint: {} as Schemas['Fingerprint'],
    members: members.map((member) => ({ match: 'exact', differences: [], ...member })),
  }
}

describe('the sources store', () => {
  let server: MediaServer
  let editorOpen: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    setActivePinia(createPinia())
    server = new MediaServer()
      .add('/media/a.mkv')
      .add('/media/b.mkv', source('/media/b.mkv', ['The container reports no duration.']))
      .add('/media/c.mkv')
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    const editor = useEditorStore()
    editorOpen = vi.spyOn(editor, 'open').mockResolvedValue()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  function deletes(): string[] {
    return server.requests
      .filter((request) => request.method === 'DELETE')
      .map((request) => request.path.replace('/api/sources/', ''))
  }

  describe('open', () => {
    it('probes the paths and adds their sources with their warnings, not other clients’ ones', async () => {
      server.registry = [
        { id: 'other', path: '/media/other.mkv', source: source('/media/other.mkv') },
      ]
      const sources = useSourcesStore()
      const found = await sources.open(['/media/a.mkv', '/media/b.mkv'])
      expect(server.last().request.body).toEqual({
        paths: ['/media/a.mkv', '/media/b.mkv'],
        recursive: false,
      })
      expect(found.map((entry) => entry.id)).toEqual([idOf('/media/a.mkv'), idOf('/media/b.mkv')])
      expect(sources.entries.map((entry) => entry.path)).toEqual(['/media/a.mkv', '/media/b.mkv'])
      expect(sources.entries[1]?.source?.warnings).toEqual(['The container reports no duration.'])
    })

    it('asks for the subfolders when recursive', async () => {
      server.folders.set('/media/show', ['/media/a.mkv'])
      await useSourcesStore().open(['/media/show'], { recursive: true })
      expect(server.last().request.body).toEqual({ paths: ['/media/show'], recursive: true })
    })

    it('shows the task’s progress as 0 to 1 while it runs, then drops the run', async () => {
      server.auto = false
      const sources = useSourcesStore()
      const opening = sources.open(['/media/a.mkv'])
      await settle()
      expect(sources.probing).toEqual([
        { taskId: server.last().taskId, paths: ['/media/a.mkv'], progress: null, message: null },
      ])
      server.progress(server.last(), { progress: 50, message: '1/2 files' })
      await settle()
      expect(sources.probing[0]).toMatchObject({ progress: 0.5, message: '1/2 files' })
      server.done(server.last())
      await opening
      expect(sources.probing).toEqual([])
    })

    it('selects the first new source when none is active, with the editor’s preset', async () => {
      const sources = useSourcesStore()
      const editor = useEditorStore()
      vi.spyOn(editor, 'presetId', 'get').mockReturnValue('h264')
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      expect(sources.activeId).toBe(idOf('/media/a.mkv'))
      expect(editorOpen).toHaveBeenCalledExactlyOnceWith(idOf('/media/a.mkv'), 'h264')
    })

    it('keeps the active source when more are opened', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv'])
      await sources.open(['/media/b.mkv'])
      expect(sources.activeId).toBe(idOf('/media/a.mkv'))
      expect(editorOpen).toHaveBeenCalledOnce()
    })

    it('leaves the selection with select: false', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv'], { select: false })
      expect(sources.activeId).toBeNull()
      expect(editorOpen).not.toHaveBeenCalled()
    })

    it('puts a source opened again in its place instead of adding it twice', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      server.files.set('/media/a.mkv', source('/media/a.mkv', ['changed']))
      await sources.open(['/media/a.mkv'])
      expect(sources.entries.map((entry) => entry.path)).toEqual(['/media/a.mkv', '/media/b.mkv'])
      expect(sources.entries[0]?.source?.warnings).toEqual(['changed'])
    })

    it('lists the paths that gave no source in one warning toast', async () => {
      const sources = useSourcesStore()
      const found = await sources.open(['/media/a.mkv', '/media/gone.mkv'])
      expect(found.map((entry) => entry.path)).toEqual(['/media/a.mkv'])
      expect(useToastStore().items).toEqual([
        expect.objectContaining({
          severity: 'warn',
          summary: 'Some paths could not be opened',
          detail: 'gone.mkv: The file does not exist.',
        }),
      ])
    })

    it('shows a failed probe task as an error toast and adds nothing', async () => {
      server.auto = false
      const sources = useSourcesStore()
      const opening = sources.open(['/media/a.mkv'])
      await settle()
      server.end(server.last(), { state: 'failed', error: 'ffprobe crashed' })
      expect(await opening).toEqual([])
      expect(sources.entries).toEqual([])
      expect(useToastStore().items).toEqual([
        expect.objectContaining({ severity: 'error', detail: 'ffprobe crashed' }),
      ])
    })

    it('adds nothing and says nothing for a cancelled probe task', async () => {
      server.auto = false
      const sources = useSourcesStore()
      const opening = sources.open(['/media/a.mkv'])
      await settle()
      server.end(server.last(), { state: 'cancelled' })
      expect(await opening).toEqual([])
      expect(useToastStore().items).toEqual([])
    })

    it('probes again once when the server forgot the task (it restarted)', async () => {
      server.auto = false
      const tasks = useTasksStore()
      const wait = vi.spyOn(tasks, 'wait').mockRejectedValueOnce(new TaskLostError('t1'))
      const sources = useSourcesStore()
      const opening = sources.open(['/media/a.mkv'])
      await settle()
      expect(server.probes).toHaveLength(2)
      expect(sources.probing.map((run) => run.taskId)).toEqual([server.last().taskId])
      server.done(server.last())
      expect((await opening).map((entry) => entry.path)).toEqual(['/media/a.mkv'])
      expect(wait).toHaveBeenCalledTimes(2)
    })

    it('rejects when the server forgets the task a second time', async () => {
      vi.spyOn(useTasksStore(), 'wait').mockRejectedValue(new TaskLostError('t'))
      const sources = useSourcesStore()
      await expect(sources.open(['/media/a.mkv'])).rejects.toBeInstanceOf(TaskLostError)
      expect(server.probes).toHaveLength(2)
      expect(sources.probing).toEqual([])
    })

    it('rejects with the server’s problem for a path outside the roots, and starts nothing', async () => {
      server.on('POST /api/sources', () =>
        problem(403, 'path.outside_roots', 'The path is outside the allowed folders'),
      )
      const sources = useSourcesStore()
      await expect(sources.open(['/etc/passwd'])).rejects.toBeInstanceOf(ApiError)
      expect(sources.probing).toEqual([])
      expect(sources.entries).toEqual([])
    })

    it('sends nothing for no paths', async () => {
      expect(await useSourcesStore().open([])).toEqual([])
      expect(server.requests).toEqual([])
    })
  })

  describe('grouping', () => {
    it('groups the open sources at the standard level', async () => {
      const grouping = {
        groups: [group('Show S01', [{ path: '/media/a.mkv' }, { path: '/media/b.mkv' }])],
        issues: [],
      }
      server.groupings.push(grouping)
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      const request = server.requests.find((r) => r.path === '/api/batch/group')
      expect(request?.body).toEqual({
        source_ids: [idOf('/media/a.mkv'), idOf('/media/b.mkv')],
        level: GROUP_LEVEL,
      })
      expect(GROUP_LEVEL).toBe('standard')
      expect(sources.grouping).toEqual(grouping)
    })

    it('leaves out a source whose file changed or is gone, and needs two sources', async () => {
      server.add('/media/stale.mkv')
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/stale.mkv'])
      expect(server.count('POST /api/batch/group')).toBe(1)
      sources.entries = sources.entries.map((entry) =>
        entry.path === '/media/stale.mkv' ? { ...entry, source: null } : entry,
      )
      await sources.open(['/media/b.mkv'])
      const last = server.requests.findLast((r) => r.path === '/api/batch/group')
      expect((last?.body as { source_ids: string[] } | undefined)?.source_ids).toEqual([
        idOf('/media/a.mkv'),
        idOf('/media/b.mkv'),
      ])
      await sources.remove(idOf('/media/b.mkv'))
      expect(sources.grouping).toBeNull()
      expect(server.count('POST /api/batch/group')).toBe(2)
    })

    it('keeps the newest grouping when an older answer comes last', async () => {
      const older = deferred<Schemas['BatchGrouping']>()
      const newer = {
        groups: [group('newer', [{ path: '/media/a.mkv' }, { path: '/media/c.mkv' }])],
        issues: [],
      }
      let calls = 0
      server.on('POST /api/batch/group', () => (++calls === 1 ? older.promise : newer))
      const sources = useSourcesStore()
      const first = sources.open(['/media/a.mkv', '/media/b.mkv'])
      await vi.waitFor(() => expect(calls).toBe(1))
      await sources.open(['/media/c.mkv'])
      older.resolve({ groups: [group('older', [])], issues: [] })
      await first
      expect(sources.grouping).toEqual(newer)
    })

    it('has no grouping when the server cannot group, and says nothing', async () => {
      server.on('POST /api/batch/group', () => problem(409, 'source.stale', 'Stale'))
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      expect(sources.grouping).toBeNull()
      expect(useToastStore().items).toEqual([])
    })
  })

  describe('select', () => {
    it('opens the source in the editor with the editor’s preset', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      vi.spyOn(useEditorStore(), 'presetId', 'get').mockReturnValue('h264')
      await sources.select(idOf('/media/b.mkv'))
      expect(sources.activeId).toBe(idOf('/media/b.mkv'))
      expect(editorOpen).toHaveBeenLastCalledWith(idOf('/media/b.mkv'), 'h264')
    })

    it('does not draft the source the editor has open again (its edits stay)', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv'])
      const editor = useEditorStore()
      editor.target = { kind: 'job', sourceId: idOf('/media/a.mkv'), job: {} as never }
      await sources.select(idOf('/media/a.mkv'))
      expect(editorOpen).toHaveBeenCalledOnce()
    })

    it('when the draft fails, the editor’s source is active again and the error goes on', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      const editor = useEditorStore()
      editor.target = { kind: 'job', sourceId: idOf('/media/a.mkv'), job: {} as never }
      const refused = new ApiError(409, {
        type: 'about:blank',
        title: 'Stale',
        status: 409,
        code: 'source.stale',
      })
      editorOpen.mockRejectedValueOnce(refused)
      await expect(sources.select(idOf('/media/b.mkv'))).rejects.toBe(refused)
      expect(sources.activeId).toBe(idOf('/media/a.mkv'))
    })

    it('ignores an id that is not open', async () => {
      const sources = useSourcesStore()
      await sources.select('nope')
      expect(sources.activeId).toBeNull()
      expect(editorOpen).not.toHaveBeenCalled()
    })
  })

  describe('remove', () => {
    it('forgets the source on the server and here; the editor closes with its source', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      const editor = useEditorStore()
      editor.target = { kind: 'job', sourceId: idOf('/media/a.mkv'), job: {} as never }
      const close = vi.spyOn(editor, 'close')
      await sources.remove(idOf('/media/a.mkv'))
      expect(deletes()).toEqual([idOf('/media/a.mkv')])
      expect(sources.entries.map((entry) => entry.path)).toEqual(['/media/b.mkv'])
      expect(sources.activeId).toBeNull()
      expect(close).toHaveBeenCalledOnce()
    })

    it('keeps the active source and the editor when another one goes', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      const editor = useEditorStore()
      editor.target = { kind: 'job', sourceId: idOf('/media/a.mkv'), job: {} as never }
      const close = vi.spyOn(editor, 'close')
      await sources.remove(idOf('/media/b.mkv'))
      expect(sources.activeId).toBe(idOf('/media/a.mkv'))
      expect(close).not.toHaveBeenCalled()
    })

    it('removes a source the server forgot already, without a toast', async () => {
      server.on(`DELETE /api/sources/${idOf('/media/a.mkv')}`, () =>
        problem(404, 'source.unknown', 'No source'),
      )
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv'])
      await sources.remove(idOf('/media/a.mkv'))
      expect(sources.entries).toEqual([])
      expect(useToastStore().items).toEqual([])
    })

    it('keeps a source the server refused to forget, shows why and rejects', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      server.on(`DELETE /api/sources/${idOf('/media/a.mkv')}`, () =>
        problem(500, 'server.error', 'It broke'),
      )
      await expect(
        sources.removeMany([idOf('/media/a.mkv'), idOf('/media/b.mkv')]),
      ).rejects.toBeInstanceOf(ApiError)
      expect(sources.entries.map((entry) => entry.path)).toEqual(['/media/a.mkv'])
      expect(useToastStore().items).toEqual([expect.objectContaining({ summary: 'It broke' })])
    })
  })

  describe('ensure', () => {
    it('gives an open source without a request', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv'])
      const before = server.requests.length
      expect((await sources.ensure('/media/a.mkv')).id).toBe(idOf('/media/a.mkv'))
      expect(server.requests).toHaveLength(before)
    })

    it('probes a path that is not open and leaves the selection to the caller', async () => {
      const sources = useSourcesStore()
      const entry = await sources.ensure('/media/c.mkv')
      expect(entry).toMatchObject({ id: idOf('/media/c.mkv'), path: '/media/c.mkv' })
      expect(sources.activeId).toBeNull()
      expect(editorOpen).not.toHaveBeenCalled()
    })

    it('rejects when the path gives no source', async () => {
      await expect(useSourcesStore().ensure('/media/gone.mkv')).rejects.toBeInstanceOf(
        SourceOpenError,
      )
    })
  })

  describe('after a server restart', () => {
    it('probes every open path again in one task and keeps the active source', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv', '/media/c.mkv'])
      await sources.select(idOf('/media/b.mkv'))
      server.registry = []
      server.files.delete('/media/c.mkv')
      await sources.onServerRestart()
      expect(server.last().request.body).toEqual({
        paths: ['/media/a.mkv', '/media/b.mkv', '/media/c.mkv'],
        recursive: false,
      })
      expect(sources.activeId).toBe(idOf('/media/b.mkv'))
      expect(sources.entries.map((entry) => [entry.path, entry.source !== null])).toEqual([
        ['/media/a.mkv', true],
        ['/media/b.mkv', true],
        ['/media/c.mkv', false],
      ])
    })

    it('does nothing without open sources', async () => {
      await useSourcesStore().onServerRestart()
      expect(server.requests).toEqual([])
    })
  })

  describe('refresh', () => {
    it('takes the server’s copies and probes again the sources it forgot', async () => {
      const sources = useSourcesStore()
      await sources.open(['/media/a.mkv', '/media/b.mkv'])
      server.registry = [{ id: idOf('/media/a.mkv'), path: '/media/a.mkv', source: null }]
      await sources.refresh()
      expect(server.last().request.body).toEqual({ paths: ['/media/b.mkv'], recursive: false })
      expect(sources.entries.map((entry) => [entry.path, entry.source !== null])).toEqual([
        ['/media/a.mkv', false],
        ['/media/b.mkv', true],
      ])
    })
  })

  describe('pick', () => {
    it('opens the files the platform’s picker gives', async () => {
      const pickFiles = vi.spyOn(platform, 'pickFiles').mockResolvedValue(['/media/a.mkv'])
      const sources = useSourcesStore()
      await sources.pick()
      expect(pickFiles).toHaveBeenCalledWith({ multiple: true })
      expect(sources.entries.map((entry) => entry.path)).toEqual(['/media/a.mkv'])
    })

    it('opens the folder the platform’s folder picker gives, with its subfolders when asked', async () => {
      server.folders.set('/media/show', ['/media/a.mkv', '/media/b.mkv'])
      vi.spyOn(platform, 'pickFolder').mockResolvedValue('/media/show')
      const sources = useSourcesStore()
      await sources.pickFolder({ recursive: true })
      expect(server.last().request.body).toEqual({ paths: ['/media/show'], recursive: true })
      expect(sources.entries).toHaveLength(2)
    })

    it('sends nothing when the folder picker was cancelled', async () => {
      vi.spyOn(platform, 'pickFolder').mockResolvedValue(null)
      await useSourcesStore().pickFolder()
      expect(server.requests).toEqual([])
    })
  })
})
