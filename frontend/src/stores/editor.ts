import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'

import { api, ApiError, apiQuiet, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type {
  FieldChange,
  Fix,
  JobDraft,
  JobSettings,
  JobTemplate,
  JsonPatchOp,
  Preset,
} from '@/api/types'
import {
  EMPTY_HISTORY,
  endRun,
  type History,
  record,
  redoStep,
  type Step,
  undoStep,
} from '@/editor/history'
import { latestRequest } from '@/editor/latest'
import { applyOps, cloneJson, deepFreeze, diffJson, PatchError } from '@/editor/patch'
import { valueAt } from '@/editor/pointer'
import { templateOf } from '@/editor/template'

import { usePresetsStore } from './presets'
import { hasPointer, useSettingsStore } from './settings'
import { useToastStore } from './toasts'

export { pathOf, pointerOf } from '@/editor/pointer'
export { PatchError } from '@/editor/patch'

/**
 * What the tabs edit: one job, or a batch group (a template with per-file overrides). The
 * tabs read and write through the store's `get`, `set` and `patch`, so they work for both.
 */
export type EditorTarget =
  | { kind: 'job'; sourceId: string; job: JobSettings }
  | {
      kind: 'group'
      groupId: string
      template: JobTemplate
      /** Per source id: a JSON patch on that file's job. */
      overrides: Record<string, JsonPatchOp[]>
    }

export interface PatchOptions {
  /** Patches in a row with the same key make one undo step (a slider drag, typing in a field). */
  coalesce?: string
}

/**
 * An edit that the screen shows and the job does not have yet: a field that writes into the job
 * once the server has answered. An add to the queue waits for it. A reactive object, so that a
 * change of `failure` is seen.
 */
export interface PendingEdit {
  /** Sends what the edit waits for at once: no debounce, and once more after a failure. */
  flush(): void
  /** Why the edit could not reach the job (its request failed); `null` while it is on its way. */
  readonly failure: string | null
}

/** Milliseconds from the last edit to `presets/diff` and `jobs/validate`. */
export const EDIT_DEBOUNCE = 250

const TOAST_LIFE = 10_000

/** `jobs/draft`, frozen. */
async function drafted(sourceId: string, preset: string | null): Promise<JobDraft> {
  const answer = unwrap(
    await api.POST('/api/jobs/draft', { body: { source_id: sourceId, preset_id: preset } }),
  )
  return deepFreeze(cloneJson(answer))
}

function toast(summary: string, detail: string): void {
  useToastStore().push({ severity: 'error', summary, detail, life: TOAST_LIFE })
}

/**
 * The job being edited. It is frozen: every change goes through `patch` or `set`, so that it is
 * an undo step and is validated.
 */
export const useEditorStore = defineStore('editor', () => {
  const presets = usePresetsStore()
  const settings = useSettingsStore()

  const target = shallowRef<EditorTarget | null>(null)
  /** The last `jobs/draft` answer for the open source: track decisions, naming, notes. */
  const draft = shallowRef<JobDraft | null>(null)
  const loading = ref(false)
  /** `presets/diff` of `currentTemplate` against the preset (the *modified* marker). */
  const presetChanges = shallowRef<FieldChange[]>([])
  /** +1 for each new target (`open`, `loadJob`, `close`): what was known of the last one is void. */
  const session = ref(0)
  const history = shallowRef<History>(EMPTY_HISTORY)
  /** The job's preset as `GET /api/presets/{id}` gave it, while the presets store lacks it. */
  const fetchedPreset = shallowRef<Preset | null>(null)
  const pendingEdits = shallowRef<readonly PendingEdit[]>([])

  const job = computed<JobSettings | null>(() =>
    target.value?.kind === 'job' ? target.value.job : null,
  )
  /** The preset the job was drafted from (an undone preset change brings the old one back). */
  const presetId = computed<string | null>(() => job.value?.preset_id ?? null)
  const jobPreset = computed<Preset | null>(() => {
    const id = presetId.value
    if (id === null) return null
    return presets.byId(id) ?? (fetchedPreset.value?.id === id ? fetchedPreset.value : null)
  })
  /**
   * The preset-level settings of the target (for `presets/diff` and *Save as preset*); `null`
   * while the job's preset is not known.
   */
  const currentTemplate = computed<JobTemplate | null>(() => {
    const current = job.value
    const base = jobPreset.value
    if (current === null || base === null) return null
    return templateOf(current, base, settings.settings?.output?.naming ?? null)
  })
  const modified = computed(() => presetChanges.value.length > 0)
  const canUndo = computed(() => history.value.done.length > 0)
  const canRedo = computed(() => history.value.undone.length > 0)
  /** Edits on the screen are on their way into the job. */
  const editing = computed(() => pendingEdits.value.some((edit) => edit.failure === null))
  /** Why an edit on the screen could not reach the job; `null` when none failed. */
  const editFailure = computed(
    () => pendingEdits.value.find((edit) => edit.failure !== null)?.failure ?? null,
  )

  // Each open, preset change, loadJob and close counts: an older one's answer is dropped.
  let loads = 0
  const stepDrafts = new WeakMap<Step, { before: JobDraft | null; after: JobDraft | null }>()

  async function load<T>(request: () => Promise<T>, apply: (value: T) => void): Promise<void> {
    const mine = ++loads
    loading.value = true
    try {
      const value = await request()
      if (mine === loads) apply(value)
    } finally {
      if (mine === loads) loading.value = false
    }
  }

  // The validation watches the target: the draft and the session must be in place first.
  function place(next: EditorTarget | null, nextDraft: JobDraft | null, newSession: boolean): void {
    if (newSession) {
      session.value += 1
      presetChanges.value = []
      // An edit of the last job never reaches this one.
      pendingEdits.value = []
    }
    draft.value = nextDraft
    target.value = next
    if (newSession) refreshPresetChanges()
  }

  /**
   * Drafts the source with the preset (default: the default preset). Clears the history.
   * Rejects with the `ApiError` of a failed draft (already shown as a toast); the editor keeps
   * what it had.
   */
  async function open(sourceId: string, preset?: string | null): Promise<void> {
    await load(
      () => drafted(sourceId, preset ?? presets.defaultId ?? null),
      (answer) => {
        history.value = EMPTY_HISTORY
        place({ kind: 'job', sourceId, job: answer.job }, answer, true)
      },
    )
  }

  /** Drafts the open source again with another preset; one undo step. Rejects as `open`. */
  async function applyPreset(preset: string): Promise<void> {
    const opened = target.value
    if (opened?.kind !== 'job') throw new Error('editor.applyPreset: no job is open')
    await load(
      () => drafted(opened.sourceId, preset),
      (answer) => {
        const current = target.value
        if (current?.kind !== 'job') return
        const last = history.value.done.at(-1)
        history.value = record(history.value, current.job, answer.job)
        const step = history.value.done.at(-1)
        if (step !== undefined && step !== last) {
          stepDrafts.set(step, { before: draft.value, after: answer })
        }
        diffAtOnce = true
        place({ ...current, job: answer.job }, answer, false)
      },
    )
  }

  /**
   * A queued job back into the editor: its source is opened when it is not, and made the active
   * one. Clears the history. Rejects when the source cannot be opened.
   */
  async function loadJob(settingsJob: JobSettings): Promise<void> {
    const loaded = deepFreeze(cloneJson(settingsJob))
    await load(
      async () => {
        // Imported here: the sources store opens sources in the editor, a static import is a cycle.
        const { useSourcesStore } = await import('./sources')
        const sources = useSourcesStore()
        return { sources, entry: await sources.ensure(loaded.source.path) }
      },
      ({ sources, entry }) => {
        history.value = EMPTY_HISTORY
        place({ kind: 'job', sourceId: entry.id, job: loaded }, null, true)
        sources.activeId = entry.id
      },
    )
  }

  /** The value at a JSON pointer of the target's job, or `undefined`. */
  function get(pointer: string): unknown {
    return job.value === null ? undefined : valueAt(job.value, pointer)
  }

  /**
   * One undo step (or part of the current one, see `PatchOptions.coalesce`). A patch that does
   * not apply throws `PatchError` and changes nothing.
   */
  function patch(ops: JsonPatchOp[], options?: PatchOptions): void {
    const current = target.value
    if (current?.kind !== 'job') throw new Error('editor.patch: no job is open')
    const next = applyOps(current.job, ops)
    const key = options?.coalesce ?? null
    if (diffJson(current.job, next).length === 0) {
      if (key !== history.value.run?.key) history.value = endRun(history.value)
      return
    }
    history.value = record(history.value, current.job, next, key)
    target.value = { ...current, job: next }
  }

  /** `patch` with one `replace` (an `add` where the member is missing). */
  function set(pointer: string, value: unknown, options?: PatchOptions): void {
    const op = job.value !== null && hasPointer(job.value, pointer) ? 'replace' : 'add'
    patch([{ op, path: pointer, value } as JsonPatchOp], options)
  }

  /** Ends the coalescing run: the next patch starts a step of its own (a slider let go). */
  function endCoalescing(): void {
    history.value = endRun(history.value)
  }

  /**
   * A validation fix: `job` patches the job (one undo step), `settings` the server settings.
   * A fix that cannot be applied is a toast; the promise still resolves.
   */
  async function applyFix(fix: Fix): Promise<void> {
    if (fix.target === 'template') {
      throw new Error('editor.applyFix: a template fix needs a group target')
    }
    if (fix.target === 'settings') {
      try {
        await settings.update(fix.patch)
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
        toast(text('editor.fixFailed'), error.problem.detail ?? error.problem.title)
      }
      return
    }
    try {
      patch(fix.patch)
    } catch (error) {
      if (!(error instanceof PatchError)) throw error
      toast(text('editor.fixFailed'), text('editor.fixStale'))
    }
  }

  function move(
    moved: { step: Step; history: History } | null,
    ops: (step: Step) => JsonPatchOp[],
    side: 'before' | 'after',
  ): void {
    const current = target.value
    if (moved === null || current?.kind !== 'job') return
    let next: JobSettings
    try {
      next = applyOps(current.job, ops(moved.step))
    } catch (error) {
      if (!(error instanceof PatchError)) throw error
      // The job was changed outside the history: its steps no longer fit it.
      console.error('editor: the undo history does not fit the job and was cleared', error)
      history.value = EMPTY_HISTORY
      return
    }
    history.value = moved.history
    const drafts = stepDrafts.get(moved.step)
    if (drafts !== undefined) draft.value = drafts[side]
    target.value = { ...current, job: next }
  }

  function undo(): void {
    move(undoStep(history.value), (step) => step.undo, 'before')
  }

  function redo(): void {
    move(redoStep(history.value), (step) => step.redo, 'after')
  }

  /** No job. `keepLoading`: a draft on its way (another source being opened) still comes in. */
  function close(options?: { keepLoading?: boolean }): void {
    if (options?.keepLoading !== true) {
      loads += 1
      loading.value = false
    }
    history.value = EMPTY_HISTORY
    place(null, null, true)
  }

  /** Until `endEdit`, `editing` (or `editFailure`) says that the job lacks what the screen shows. */
  function beginEdit(edit: PendingEdit): void {
    if (!pendingEdits.value.includes(edit)) pendingEdits.value = [...pendingEdits.value, edit]
  }

  function endEdit(edit: PendingEdit): void {
    if (pendingEdits.value.includes(edit)) {
      pendingEdits.value = pendingEdits.value.filter((other) => other !== edit)
    }
  }

  /** Asks each pending edit to reach the job at once (an add to the queue is waiting). */
  function flushEdits(): void {
    for (const edit of pendingEdits.value) edit.flush()
  }

  // A preset that the presets store does not hold yet (it loads later, or never in a test).
  let presetReads = 0
  watch(presetId, async (id) => {
    const mine = ++presetReads
    if (id === null || presets.byId(id) !== undefined || fetchedPreset.value?.id === id) return
    let found: Preset | null = null
    try {
      const result = await apiQuiet.GET('/api/presets/{preset_id}', {
        params: { path: { preset_id: id } },
      })
      found = result.response.ok ? (result.data ?? null) : null
    } catch {
      found = null
    }
    if (mine === presetReads) fetchedPreset.value = found
  })

  const diff = latestRequest<FieldChange[]>({
    // Scheduled only while both are known: losing one cancels it.
    async send(signal) {
      const body = {
        template: currentTemplate.value as JobTemplate,
        preset_id: presetId.value as string,
      }
      return unwrap(await apiQuiet.POST('/api/presets/diff', { body, signal }))
    },
    done(changes) {
      presetChanges.value = changes
    },
    failed(error) {
      // The preset is gone: nothing to be modified against. Other failures keep the last answer.
      if (error instanceof ApiError && error.status === 404) presetChanges.value = []
    },
  })

  /** What `presets/diff` depends on, as one string: an edit that does not change it sends nothing. */
  const diffKey = computed(() => {
    const template = currentTemplate.value
    return template === null ? null : JSON.stringify([template, jobPreset.value])
  })
  // A preset change (or a preset that has just been read) is diffed at once, an edit debounced.
  let diffAtOnce = false
  let diffedPreset: string | null = null

  function sendDiff(delay: number): void {
    if (diffKey.value === null) {
      diff.cancel()
      presetChanges.value = []
      return
    }
    diff.schedule(delay)
    diffAtOnce = false
  }

  /** Asks `presets/diff` again at once (after the preset was saved, for example). */
  function refreshPresetChanges(): void {
    sendDiff(0)
  }

  watch(
    diffKey,
    () => {
      if (presetId.value !== diffedPreset) {
        diffedPreset = presetId.value
        presetChanges.value = []
        diffAtOnce = true
      }
      sendDiff(diffAtOnce ? 0 : EDIT_DEBOUNCE)
    },
    { flush: 'sync' },
  )

  return {
    target,
    draft,
    presetId,
    loading,
    presetChanges,
    session,
    job,
    preset: jobPreset,
    currentTemplate,
    modified,
    canUndo,
    canRedo,
    editing,
    editFailure,
    open,
    applyPreset,
    loadJob,
    get,
    patch,
    set,
    endCoalescing,
    applyFix,
    undo,
    redo,
    close,
    beginEdit,
    endEdit,
    flushEdits,
    refreshPresetChanges,
  }
})
