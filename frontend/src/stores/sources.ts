import { defineStore } from 'pinia'
import { computed, reactive, ref, watch } from 'vue'

import { api, ApiError, apiQuiet, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type { Schemas, SourceEntry, TaskInfo } from '@/api/types'
import { notBuilt } from '@/notBuilt'
import { platform } from '@/platform'

import { useEditorStore } from './editor'
import { TaskLostError, useTasksStore } from './tasks'
import { useToastStore } from './toasts'

/** A probe that is still running: one task for the paths of one `open`. */
export interface ProbeRun {
  taskId: string
  paths: string[]
  /** 0 to 1, or `null` when the task gives none. */
  progress: number | null
  message: string | null
}

/** A path that gave no source (the result of `POST /api/sources`). */
interface ProbeFailure {
  path: string
  code: string
  message: string
  detail?: string | null
}

interface ProbeSummary {
  sources: { id: string; path: string }[]
  errors: ProbeFailure[]
}

/** The default strictness: type, codec, channels, language, role and order. */
export const GROUP_LEVEL: Schemas['BatchGroupRequest']['level'] = 'standard'

const TOAST_LIFE = 10_000

/** A path that gave no source; the reason was shown as a toast already. */
export class SourceOpenError extends Error {
  constructor(readonly path: string) {
    super(text('sources.errors.noSource', { path }))
    this.name = 'SourceOpenError'
  }
}

async function startProbe(paths: string[], recursive: boolean): Promise<string> {
  const accepted = unwrap(await api.POST('/api/sources', { body: { paths, recursive } }))
  return accepted.task_id
}

/** The server's sources by id (other clients' too). */
async function listed(): Promise<Map<string, SourceEntry>> {
  const list = unwrap(await api.GET('/api/sources'))
  return new Map(list.map((entry) => [entry.id, entry]))
}

function name(path: string): string {
  return path.split(/[/\\]/).findLast((part) => part !== '') ?? path
}

/** The message and its detail: after a sentence (ffprobe's "… (exit code 1).") a space, else ": ". */
function reason(failure: ProbeFailure): string {
  if (!failure.detail) return failure.message
  const joiner = /[.!?…]$/.test(failure.message) ? ' ' : ': '
  return `${failure.message}${joiner}${failure.detail}`
}

/** The opened sources, the active one, the probes that run, and the batch grouping. */
export const useSourcesStore = defineStore('sources', () => {
  const tasks = useTasksStore()
  const toasts = useToastStore()
  const editor = useEditorStore()

  /** In the order they were opened. */
  const entries = ref<SourceEntry[]>([])
  const activeId = ref<string | null>(null)
  const probing = ref<ProbeRun[]>([])
  /** `POST /api/batch/group` over `entries` (the panel's collapsible groups). */
  const grouping = ref<Schemas['BatchGrouping'] | null>(null)

  const active = computed<SourceEntry | null>(
    () => entries.value.find((entry) => entry.id === activeId.value) ?? null,
  )

  // The run objects are changed in place: the getter reads only the task ids, so it is not
  // triggered again by these writes.
  watch(
    () => probing.value.map((run) => tasks.tasks[run.taskId]),
    (infos) => {
      probing.value.forEach((run, index) => {
        const info = infos[index]
        if (info === undefined) return
        run.progress = typeof info.progress === 'number' ? info.progress / 100 : null
        run.message = info.message ?? null
      })
    },
  )

  function toast(severity: 'warn' | 'error', summary: string, detail?: string): void {
    toasts.push({ severity, summary, detail, life: TOAST_LIFE })
  }

  /**
   * One probe task with its progress in `probing`; `null` when the task did not end `done`
   * (shown as a toast). A server that forgot the task (it restarted) is asked once more.
   */
  async function probe(
    paths: string[],
    recursive: boolean,
    again = true,
  ): Promise<ProbeSummary | null> {
    const run = reactive<ProbeRun>({
      taskId: await startProbe(paths, recursive),
      paths,
      progress: null,
      message: null,
    })
    probing.value.push(run)
    let task: TaskInfo
    try {
      task = await tasks.wait(run.taskId)
    } catch (error) {
      if (!(error instanceof TaskLostError) || !again) throw error
      return probe(paths, recursive, false)
    } finally {
      probing.value = probing.value.filter((other) => other.taskId !== run.taskId)
    }
    if (task.state === 'done') return task.result as unknown as ProbeSummary
    if (task.state === 'failed') {
      toast('error', text('sources.errors.probeFailed'), task.error ?? undefined)
    }
    return null
  }

  function reportFailures(failures: ProbeFailure[]): void {
    if (failures.length === 0) return
    const lines = failures.map((failure) => `${name(failure.path)}: ${reason(failure)}`)
    toast('warn', text('sources.errors.notOpened'), lines.join('\n'))
  }

  /** Puts each found entry in its place (same id), or after the others. */
  function merge(found: SourceEntry[]): void {
    const next = [...entries.value]
    for (const entry of found) {
      const index = next.findIndex((other) => other.id === entry.id)
      if (index === -1) next.push(entry)
      else next[index] = entry
    }
    entries.value = next
  }

  // The newest request wins: an older answer describes sources that changed since.
  let groupings = 0

  async function regroup(): Promise<void> {
    const mine = ++groupings
    const ids = entries.value.filter((entry) => entry.source !== null).map((entry) => entry.id)
    if (ids.length < 2) {
      grouping.value = null
      return
    }
    let answer: Schemas['BatchGrouping'] | null = null
    try {
      answer = unwrap(
        await apiQuiet.POST('/api/batch/group', { body: { source_ids: ids, level: GROUP_LEVEL } }),
      )
    } catch (error) {
      // Without a grouping the panel lists the sources one by one.
      if (!(error instanceof ApiError)) throw error
    }
    if (mine === groupings) grouping.value = answer
  }

  /**
   * Probes the paths (files or folders; a task), adds the new sources, and selects the first
   * one when none is active (`select: false` leaves the selection). Resolves with the sources
   * of these paths; the paths that gave none are a toast.
   */
  async function open(
    paths: string[],
    options?: { recursive?: boolean; select?: boolean },
  ): Promise<SourceEntry[]> {
    if (paths.length === 0) return []
    const summary = await probe(paths, options?.recursive ?? false)
    if (summary === null) return []
    reportFailures(summary.errors)
    if (summary.sources.length === 0) return []
    const known = await listed()
    const found = summary.sources.map(
      (probed) => known.get(probed.id) ?? { id: probed.id, path: probed.path, source: null },
    )
    merge(found)
    await regroup()
    const [first] = found
    if (first !== undefined && activeId.value === null && options?.select !== false) {
      try {
        await select(first.id)
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
      }
    }
    return found
  }

  /** `platform.pickFiles`, then `open` (`Ctrl+O`). */
  async function pick(): Promise<void> {
    const paths = await platform.pickFiles({ multiple: true })
    if (paths.length > 0) await open(paths)
  }

  /** `platform.pickFolder`, then `open` of its media files (and its subfolders' with `recursive`). */
  async function pickFolder(options?: { recursive?: boolean }): Promise<void> {
    const folder = await platform.pickFolder()
    if (folder !== null) await open([folder], { recursive: options?.recursive ?? false })
  }

  /**
   * The source of this path, probed first when it is not open; the selection stays. Rejects
   * with `SourceOpenError` when the path gives no source.
   */
  async function ensure(path: string): Promise<SourceEntry> {
    const known = entries.value.find((entry) => entry.path === path)
    if (known !== undefined) return known
    const [found] = await open([path], { select: false })
    if (found === undefined) throw new SourceOpenError(path)
    return found
  }

  /**
   * Makes the source active and opens it in the editor with the editor's preset, so the preset
   * carries over from one source to the next. The source open in the editor is left as it is
   * (its edits stay). When the draft fails (the `ApiError` is a toast), the editor's source is
   * the active one again, and the error is rethrown.
   */
  async function select(id: string): Promise<void> {
    if (!entries.value.some((entry) => entry.id === id)) return
    const target = editor.target
    if (activeId.value === id && target?.kind === 'job' && target.sourceId === id) return
    activeId.value = id
    try {
      await editor.open(id, editor.presetId)
    } catch (error) {
      if (activeId.value === id) {
        const current = editor.target
        activeId.value = current?.kind === 'job' ? current.sourceId : null
      }
      throw error
    }
  }

  /**
   * Forgets the sources here and on the server; the editor closes when its source goes. A
   * refused removal is a toast and rejects, after the others are gone.
   */
  async function removeMany(ids: string[]): Promise<void> {
    const results = await Promise.allSettled(ids.map((id) => forget(id)))
    const gone = new Set(ids.filter((_, index) => results[index]?.status === 'fulfilled'))
    entries.value = entries.value.filter((entry) => !gone.has(entry.id))
    const target = editor.target
    const activeGone = activeId.value !== null && gone.has(activeId.value)
    // A removed active source may still be drafting: closing drops that draft too. The draft of
    // an active source that stays (selected while the editor's source goes) must still come in.
    if (activeGone) editor.close()
    else if (target?.kind === 'job' && gone.has(target.sourceId)) {
      editor.close({ keepLoading: true })
    }
    if (activeGone) activeId.value = null
    await regroup()
    const failed = results.find((result) => result.status === 'rejected')
    if (failed !== undefined) throw failed.reason
  }

  async function remove(id: string): Promise<void> {
    await removeMany([id])
  }

  // A 404 is a source the server forgot already (a restart, another tab): gone either way.
  async function forget(id: string): Promise<void> {
    try {
      const result = await apiQuiet.DELETE('/api/sources/{source_id}', {
        params: { path: { source_id: id } },
      })
      if (result.response.status !== 404) unwrap(result)
    } catch (error) {
      if (error instanceof ApiError) {
        toast('error', error.problem.title, error.problem.detail ?? undefined)
      }
      throw error
    }
  }

  /** Probes the entries' paths again and puts the answers in their places. */
  async function reprobe(stale: SourceEntry[]): Promise<void> {
    const summary = await probe(
      stale.map((entry) => entry.path),
      false,
    )
    if (summary === null) return
    reportFailures(summary.errors)
    const known = await listed()
    const byPath = new Map(summary.sources.map((probed) => [probed.path, probed.id]))
    const activePath = active.value?.path ?? null
    entries.value = entries.value.map((entry) => {
      if (!stale.some((other) => other.id === entry.id)) return entry
      const id = byPath.get(entry.path)
      const found = id === undefined ? undefined : known.get(id)
      return found ?? { ...entry, source: null }
    })
    if (activePath !== null) {
      activeId.value = entries.value.find((entry) => entry.path === activePath)?.id ?? null
    }
    await regroup()
  }

  /**
   * Reads `GET /api/sources` again: each open source gets the server's copy (`source` `null`:
   * the file changed or is gone). Sources the server forgot are probed again.
   */
  async function refresh(): Promise<void> {
    const known = await listed()
    entries.value = entries.value.map((entry) => known.get(entry.id) ?? entry)
    const forgotten = entries.value.filter((entry) => !known.has(entry.id))
    if (forgotten.length > 0) await reprobe(forgotten)
    else await regroup()
  }

  /**
   * Reads one source again (`GET /api/sources/{id}`) and puts it in its place: a scan ended,
   * or an in-place edit changed the file.
   */
  // oxlint-disable-next-line unicorn/consistent-function-scoping -- a stub; it uses the store once built
  async function reload(id: string): Promise<void> {
    return notBuilt('sources.reload', id)
  }

  /** A new server instance forgot the sources: probe every open path again. */
  async function onServerRestart(): Promise<void> {
    if (entries.value.length === 0) return
    await reprobe([...entries.value])
  }

  return {
    entries,
    activeId,
    probing,
    grouping,
    active,
    open,
    pick,
    pickFolder,
    ensure,
    select,
    remove,
    removeMany,
    refresh,
    reload,
    onServerRestart,
  }
})
