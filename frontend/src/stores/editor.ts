import { defineStore } from 'pinia'
import { computed, reactive, ref, shallowRef, watch } from 'vue'

import { api, ApiError, apiQuiet, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type {
  BatchGroup,
  BatchResolution,
  FieldChange,
  Fix,
  JobDraft,
  JobSettings,
  JobTemplate,
  JsonPatchOp,
  Preset,
  Resolution,
  TemplateSection,
} from '@/api/types'
import { FULL, type Range } from '@/components/range/range'
import { panelItems } from '@/components/sources/panel'
import {
  changesTrackList,
  inJob,
  mergedResolutions,
  mergeOverride,
  ordered,
  perFileChange,
  perFilePointer,
  related,
  sectionsOf,
  within,
  withoutOps,
} from '@/editor/group'
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
import { applyOps, cloneJson, deepFreeze, diffJson, PatchError, sameJson } from '@/editor/patch'
import { pointerOf, valueAt } from '@/editor/pointer'
import { outputOptionsOf, templateOf } from '@/editor/template'

import { templateOfPreset, usePresetsStore } from './presets'
import { hasPointer, useSettingsStore } from './settings'
import type { useSourcesStore } from './sources'
import { useToastStore } from './toasts'

export { pathOf, pointerOf } from '@/editor/pointer'
export { PatchError } from '@/editor/patch'

/**
 * Where an edit of a group goes: into the template (every file), or into the shown file's
 * override (that file only).
 */
export type GroupScope = 'group' | 'file'

/** A source track rule's kind, as the matrix's columns and `TrackMatch.kind` name it. */
export type RuleKind = 'audio' | 'subtitle'

/**
 * What the tabs edit: one job, or a batch group (a template with per-file overrides). The
 * tabs read and write through the store's `get`, `set` and `patch`, so they work for both.
 */
export type EditorTarget =
  | { kind: 'job'; sourceId: string; job: JobSettings }
  | {
      kind: 'group'
      groupId: string
      /** The file the tabs show: the group's representative until another is chosen. */
      sourceId: string
      /**
       * What the tabs show and edit. Scope `group`: the template resolved in `sourceId` without
       * its override; scope `file`: that file's job with its override.
       */
      job: JobSettings
      template: JobTemplate
      /** The preset the template came from (the header's picker, the *modified* marker). */
      presetId: string | null
      /**
       * Per source id: a JSON patch on that file's document, the template plus a member `job`
       * (`/audio_rules/1/selector/stream`, `/job/output/naming/field_overrides/episode`).
       */
      overrides: Record<string, JsonPatchOp[]>
      scope: GroupScope
    }

type GroupTarget = Extract<EditorTarget, { kind: 'group' }>
type SourcesStore = ReturnType<typeof useSourcesStore>

/** What a group's undo history steps through. */
interface GroupDocument {
  template: JobTemplate
  overrides: Record<string, JsonPatchOp[]>
  presetId: string | null
}

/** A group's state, kept in the page while other files or groups are edited. */
interface GroupState {
  groupId: string
  /** Paths of the group's representative and members: they find it in a new grouping. */
  representative: string
  members: string[]
  document: GroupDocument
  sourceId: string
  scope: GroupScope
  history: History
  /** +1 for each change of `document`: a shown job asked for before the change is asked again. */
  version: number
}

/** A derive of `sections` of `job` into the state's template, one undo step. */
interface Derive {
  state: GroupState
  job: JobSettings
  sourceId: string
  sections: Set<TemplateSection>
  /** The job's output options go into the template too. */
  output: boolean
  key: string | null
  /** `endCoalescing` came while the derive was on its way: its step ends the run. */
  endRun: boolean
  /** An undo dropped the edits: the answer changes nothing. */
  dropped: boolean
  /** What goes into the same undo step. */
  change?: (document: GroupDocument) => GroupDocument
}

/** Edits of scope `group` on their way into the template: the shown job with the edits. */
interface DeriveBatch extends Derive {
  edit: { flush(): void; failure: string | null }
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

/** A group file's range, in its override. */
const FILE_RANGE = '/job/range'

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

/** An edit the group cannot take: nothing changed. */
function refuse(summary: string, detail: string): void {
  useToastStore().push({ severity: 'warn', summary, detail, life: TOAST_LIFE })
}

/** A matrix row has the fields of a draft: the tabs show its track decisions and notes. */
function draftOf(row: Resolution): JobDraft {
  return row as unknown as JobDraft
}

/** `batch/resolve` of the template in one file, with its override or without; frozen. */
async function resolved(
  client: typeof api,
  document: GroupDocument,
  sourceId: string,
  withOverride: boolean,
  signal?: AbortSignal,
): Promise<Resolution> {
  const override = withOverride ? (document.overrides[sourceId] ?? []) : []
  const body = {
    template: document.template,
    source_ids: [sourceId],
    overrides: override.length > 0 ? { [sourceId]: override } : {},
  }
  const answer = unwrap(await client.POST('/api/batch/resolve', { body, signal }))
  return deepFreeze(cloneJson(answer.rows?.[0] as Resolution))
}

/** `batch/derive`: the `sections` of `job` merged into `base`; frozen. */
async function derived(
  job: JobSettings,
  sourceId: string,
  sections: TemplateSection[],
  base: JobTemplate,
): Promise<JobTemplate> {
  const body = { job, source_id: sourceId, sections, base }
  return deepFreeze(cloneJson(unwrap(await api.POST('/api/batch/derive', { body }))))
}

function overriddenWith(
  document: GroupDocument,
  sourceId: string,
  ops: JsonPatchOp[],
): GroupDocument {
  const { [sourceId]: _old, ...others } = document.overrides
  return {
    ...document,
    overrides: ops.length > 0 ? { ...document.overrides, [sourceId]: ops } : others,
  }
}

/** The shown file's override operations on its range. */
function rangeOps(current: GroupTarget): JsonPatchOp[] {
  return (current.overrides[current.sourceId] ?? []).filter(
    (op) => op.op !== 'test' && within(op.path, FILE_RANGE),
  )
}

function representativeOf(found: BatchGroup, sources: SourcesStore): string {
  const ids = memberIdsOf(found, sources)
  return sources.entries.find((entry) => entry.path === found.representative)?.id ?? ids[0] ?? ''
}

function memberPaths(found: BatchGroup): string[] {
  return (found.members ?? []).map((member) => member.path)
}

/** The open sources of the group, in its order. */
function memberIdsOf(found: BatchGroup, sources: SourcesStore): string[] {
  return (found.members ?? []).flatMap((member) => {
    const entry = sources.entries.find((candidate) => candidate.path === member.path)
    return entry === undefined ? [] : [entry.id]
  })
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
  /** The job's preset as fetched by its id, while the presets store lacks it. */
  const fetchedPreset = shallowRef<Preset | null>(null)
  const pendingEdits = shallowRef<readonly PendingEdit[]>([])

  /** What the tabs show: the job, or the group's shown job. */
  const job = computed<JobSettings | null>(() => target.value?.job ?? null)
  /**
   * The preset the job was drafted from, or the group's (an undone preset change brings the old
   * one back).
   */
  const presetId = computed<string | null>(() => {
    const current = target.value
    return current?.kind === 'group' ? current.presetId : (current?.job.preset_id ?? null)
  })
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
    if (target.value?.kind === 'group') return target.value.template
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
        leaveGroup()
        history.value = EMPTY_HISTORY
        place({ kind: 'job', sourceId, job: answer.job }, answer, true)
      },
    )
  }

  /**
   * Drafts the open source again with another preset, keeping the job's range; in a group, the
   * template becomes the preset's and the overrides stay. One undo step. Rejects as `open`.
   */
  async function applyPreset(preset: string): Promise<void> {
    const opened = target.value
    if (opened?.kind === 'group') {
      const state = requireGroup('applyPreset')
      await settled()
      await load(
        () => presetTemplate(preset),
        (template) => {
          if (editedState() !== state) return
          // The preset was just saved from this template: only its name changes, no undo step.
          if (sameJson(template, state.document.template)) {
            state.document = deepFreeze({ ...state.document, presetId: preset })
            target.value = groupTarget(state, (target.value as GroupTarget).job)
            return
          }
          commit(state, { ...state.document, template, presetId: preset })
        },
      )
      return
    }
    if (opened?.kind !== 'job') throw new Error('editor.applyPreset: no job is open')
    await load(
      () => drafted(opened.sourceId, preset),
      (answer) => {
        const current = target.value
        if (current?.kind !== 'job') return
        // A preset has no range: the job keeps its own.
        const kept = current.job.range ?? FULL
        const next = sameJson(answer.job.range ?? FULL, kept)
          ? answer.job
          : deepFreeze({ ...answer.job, range: kept })
        const last = history.value.done.at(-1)
        history.value = record(history.value, current.job, next)
        const step = history.value.done.at(-1)
        if (step !== undefined && step !== last) {
          stepDrafts.set(step, { before: draft.value, after: answer })
        }
        diffAtOnce = true
        place({ ...current, job: next }, answer, false)
      },
    )
  }

  /**
   * Drafts the open source again as a remux-only job (every track copied) with the job's preset;
   * one undo step. `editInPlace` (default `true`) turns *Edit in place* on, also for a source that
   * is not MKV: validation then refuses it. Rejects as `open`.
   */
  async function applyRemuxDraft(options?: { editInPlace?: boolean }): Promise<void> {
    const opened = target.value
    if (opened?.kind !== 'job') throw new Error('editor.applyRemuxDraft: no job is open')
    const body = {
      source_id: opened.sourceId,
      preset_id: opened.job.preset_id ?? null,
      edit_in_place: options?.editInPlace ?? true,
    }
    await load(
      async () => deepFreeze(cloneJson(unwrap(await api.POST('/api/jobs/draft-remux', { body })))),
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
        leaveGroup()
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
   * not apply throws `PatchError` and changes nothing. In a group it goes into the template or
   * the shown file's override (the scope); one the group cannot take is a toast and changes
   * nothing.
   */
  function patch(ops: JsonPatchOp[], options?: PatchOptions): void {
    const current = target.value
    if (current === null) throw new Error('editor.patch: no job is open')
    const next = applyOps(current.job, ops)
    const key = options?.coalesce ?? null
    if (diffJson(current.job, next).length === 0) {
      if (key !== history.value.run?.key) history.value = endRun(history.value)
      return
    }
    if (current.kind === 'group') {
      if (current.scope === 'group') patchGroup(current, next, key)
      else patchFile(current, ops, next, key)
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

  /**
   * Puts a value the server worked out (a detected crop) into the open job without an undo step,
   * so an undo never takes it back out. It ends the coalescing run, whose step would otherwise
   * carry it. A group's files are not changed: their crop is detected for each file.
   */
  function amend(ops: JsonPatchOp[]): void {
    const current = target.value
    if (current === null || current.kind !== 'job') return
    history.value = endRun(history.value)
    target.value = { ...current, job: applyOps(current.job, ops) }
  }

  /** Ends the coalescing run: the next patch starts a step of its own (a slider let go). */
  function endCoalescing(): void {
    history.value = endRun(history.value)
    if (waiting !== null) waiting.endRun = true
    for (const batch of sent) batch.endRun = true
  }

  /**
   * A validation fix: `job` patches the job (one undo step), `settings` the server settings.
   * A fix that cannot be applied is a toast; the promise still resolves.
   */
  async function applyFix(fix: Fix): Promise<void> {
    if (fix.target === 'template') {
      if (target.value?.kind !== 'group') {
        throw new Error('editor.applyFix: a template fix needs a group target')
      }
      try {
        await patchTemplate(fix.patch)
      } catch (error) {
        if (!(error instanceof PatchError)) throw error
        toast(text('editor.fixFailed'), text('editor.fixStale'))
      }
      return
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
      // The job was changed outside the history, so its steps do not fit it.
      console.error('editor: the undo history does not fit the job and was cleared', error)
      history.value = EMPTY_HISTORY
      return
    }
    history.value = moved.history
    const drafts = stepDrafts.get(moved.step)
    if (drafts !== undefined) draft.value = drafts[side]
    target.value = { ...current, job: next }
  }

  /** An undo or redo while edits of scope `group` wait for their derive only drops those edits. */
  function moveGroup(
    next: (from: History) => { step: Step; history: History } | null,
    ops: (step: Step) => JsonPatchOp[],
  ): void {
    const state = requireGroup('undo')
    if (dropEdits(state)) return
    const moved = next(history.value)
    if (moved === null) return
    let document: GroupDocument
    try {
      document = applyOps(state.document, ops(moved.step))
    } catch (error) {
      if (!(error instanceof PatchError)) throw error
      console.error('editor: the undo history does not fit the group and was cleared', error)
      history.value = EMPTY_HISTORY
      return
    }
    history.value = moved.history
    state.document = document
    state.version += 1
    show(state)
  }

  function undo(): void {
    if (target.value?.kind === 'group') moveGroup(undoStep, (step) => step.undo)
    else move(undoStep(history.value), (step) => step.undo, 'before')
  }

  function redo(): void {
    // An edit waiting for its derive has cleared the steps to redo: it is not dropped.
    if (target.value?.kind === 'group') {
      if (canRedo.value) moveGroup(redoStep, (step) => step.redo)
    } else move(redoStep(history.value), (step) => step.redo, 'after')
  }

  /** No job. `keepLoading`: a draft on its way (another source being opened) still comes in. */
  function close(options?: { keepLoading?: boolean }): void {
    if (options?.keepLoading !== true) {
      loads += 1
      loading.value = false
    }
    leaveGroup()
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

  /** The group states of this page, by group id. */
  const groups = new Map<string, GroupState>()
  // Set at the first group action: the sources store imports this one, a static import is a cycle.
  const sourcesStore = shallowRef<SourcesStore | null>(null)

  async function useSources(): Promise<SourcesStore> {
    const { useSourcesStore } = await import('./sources')
    sourcesStore.value = useSourcesStore()
    return sourcesStore.value
  }

  /** The batch group being edited, as `sources.grouping` has it; `null` for a job. */
  const group = computed<BatchGroup | null>(() => {
    const current = target.value
    if (current?.kind !== 'group') return null
    return (
      sourcesStore.value?.grouping?.groups?.find((found) => found.id === current.groupId) ?? null
    )
  })
  const members = computed<string[]>(() => {
    const sources = sourcesStore.value
    return group.value === null || sources === null ? [] : memberIdsOf(group.value, sources)
  })
  /**
   * The edited group's matrix: `batch/resolve-run` of its members with the template and the
   * overrides, the rows of every file in episode order; the newest answer only.
   */
  const resolution = shallowRef<BatchResolution | null>(null)
  /** A resolve is on its way: `resolution` may describe an older template. */
  const resolving = ref(false)
  /**
   * Why the newest `batch/resolve-run` failed (the problem's detail, else its title); `null`
   * after an answer and while no group is edited. `resolution` is then the last answer.
   */
  const matrixError = ref<string | null>(null)

  function editedState(): GroupState | null {
    const current = target.value
    return current?.kind === 'group' ? (groups.get(current.groupId) ?? null) : null
  }

  function requireGroup(action: string): GroupState {
    const state = editedState()
    if (state === null) throw new Error(`editor.${action}: no group is edited`)
    return state
  }

  function groupTarget(state: GroupState, shownJob: JobSettings): GroupTarget {
    const { template, overrides, presetId: preset } = state.document
    return {
      kind: 'group',
      groupId: state.groupId,
      sourceId: state.sourceId,
      job: shownJob,
      template,
      presetId: preset,
      overrides,
      scope: state.scope,
    }
  }

  /** The last shown job the server resolved: what a failed or dropped edit goes back to. */
  let shownRow: Resolution | null = null

  function showRow(row: Resolution): void {
    const current = target.value
    if (current?.kind === 'group')
      place({ ...current, job: row.job as JobSettings }, draftOf(row), false)
  }

  const shown = latestRequest<{
    row: Resolution
    state: GroupState
    sourceId: string
    scope: GroupScope
  }>({
    async send(signal) {
      const state = requireGroup('resolve')
      const { sourceId, scope } = state
      const row = await resolved(apiQuiet, state.document, sourceId, scope === 'file', signal)
      return { row, state, sourceId, scope }
    },
    done({ row, state, sourceId, scope }) {
      if (editedState() !== state || state.sourceId !== sourceId || state.scope !== scope) return
      shownRow = row
      // The shown job has edits that the server has not seen yet.
      if (!pendingDerive(state)) showRow(row)
    },
    failed() {
      // The shown job stays as it is; the next change asks again.
    },
  })

  let matrixAsks = 0
  let matrixTimer: ReturnType<typeof setTimeout> | undefined

  /** Rejects with the `ApiError` of a failed request, without a toast. */
  async function askMatrix(): Promise<BatchResolution> {
    clearTimeout(matrixTimer)
    matrixTimer = undefined
    const state = requireGroup('resolve')
    const ids = members.value
    const overrides = Object.fromEntries(
      ids.flatMap((id) => {
        const ops = state.document.overrides[id] ?? []
        return ops.length > 0 ? [[id, ops]] : []
      }),
    )
    const body = {
      template: state.document.template,
      source_ids: ids,
      level: (group.value as BatchGroup).level,
      overrides,
    }
    const mine = ++matrixAsks
    resolving.value = true
    try {
      const answer = deepFreeze(
        mergedResolutions(unwrap(await apiQuiet.POST('/api/batch/resolve-run', { body }))),
      )
      if (mine === matrixAsks) {
        resolution.value = answer
        matrixError.value = null
      }
      return answer
    } catch (error) {
      if (error instanceof ApiError && mine === matrixAsks) {
        // The server's detail of a stale source is meant for a developer.
        matrixError.value =
          error.problem.code === 'source.stale'
            ? text('editor.group.sourceStale')
            : (error.problem.detail ?? error.problem.title)
      }
      throw error
    } finally {
      if (mine === matrixAsks) resolving.value = false
    }
  }

  function askQuietly(): void {
    // The screens show the failure (`matrixError`).
    askMatrix().catch((error: unknown) => {
      if (!(error instanceof ApiError)) throw error
    })
  }

  /** Asks for the matrix again; changes in one turn make one request. */
  function requestMatrix(): void {
    resolving.value = true
    clearTimeout(matrixTimer)
    matrixTimer = setTimeout(askQuietly, 0)
  }

  /** Asks for the matrix again at once (after a failure). */
  function retryMatrix(): void {
    requireGroup('retryMatrix')
    askQuietly()
  }

  /** The document changed: the target shows it, the shown job and the matrix are asked again. */
  function show(state: GroupState): void {
    const current = target.value
    if (current?.kind !== 'group') return
    target.value = groupTarget(state, current.job)
    shown.schedule(0)
    requestMatrix()
  }

  /** One undo step of the group's history (the edited group's, or a kept one's). */
  function commit(state: GroupState, next: GroupDocument, key: string | null = null): void {
    const edited = editedState() === state
    const recorded = record(edited ? history.value : state.history, state.document, next, key)
    state.document = deepFreeze(next)
    state.version += 1
    if (!edited) {
      state.history = recorded
      return
    }
    history.value = recorded
    show(state)
  }

  /** Leaves the edited group: its state is kept, an edit on its way still reaches it. */
  function leaveGroup(): void {
    const state = editedState()
    if (state === null) return
    state.history = history.value
    failedEdit = null
    if (waiting !== null) sendDerive()
    shown.cancel()
    matrixAsks += 1
    clearTimeout(matrixTimer)
    resolution.value = null
    resolving.value = false
    matrixError.value = null
    shownRow = null
  }

  let waiting: DeriveBatch | null = null
  /** Batches in the derive queue, not answered yet. */
  const sent = new Set<DeriveBatch>()
  let deriveTimer: ReturnType<typeof setTimeout> | undefined
  let failedEdit: PendingEdit | null = null
  // Derives and template changes run one after the other, in the order they were asked for, so
  // that a derive never writes over a change made after its edit.
  let queue: Promise<unknown> = Promise.resolve()
  let queued = 0

  function enqueue<T>(task: () => Promise<T>): Promise<T> {
    queued += 1
    const run = queue.then(task).finally(() => {
      queued -= 1
    })
    queue = run.catch(() => undefined)
    return run
  }

  function pendingDerive(state: GroupState): boolean {
    return waiting?.state === state || [...sent].some((batch) => batch.state === state)
  }

  /** The waiting edits go into the derive queue. */
  function sendDerive(): void {
    clearTimeout(deriveTimer)
    deriveTimer = undefined
    const batch = waiting
    if (batch === null) return
    waiting = null
    sent.add(batch)
    void enqueue(async () => {
      try {
        await deriveInto(batch)
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
        if (!batch.dropped) batch.edit.failure = error.problem.detail ?? error.problem.title
      } finally {
        sent.delete(batch)
      }
      if (batch.edit.failure === null) {
        endEdit(batch.edit)
        return
      }
      failedEdit = batch.edit
      if (editedState() === batch.state && !pendingDerive(batch.state) && shownRow !== null)
        showRow(shownRow)
    })
  }

  function endRunOf(state: GroupState): void {
    if (editedState() === state) history.value = endRun(history.value)
    else state.history = endRun(state.history)
  }

  /** Drops the edits that wait for their derive; the shown job goes back. */
  function dropEdits(state: GroupState): boolean {
    if (failedEdit !== null) {
      endEdit(failedEdit)
      failedEdit = null
    }
    if (!pendingDerive(state)) return false
    clearTimeout(deriveTimer)
    deriveTimer = undefined
    if (waiting !== null) endEdit(waiting.edit)
    waiting = null
    for (const batch of sent) {
      if (batch.state !== state) continue
      batch.dropped = true
      endEdit(batch.edit)
    }
    if (shownRow !== null) showRow(shownRow)
    return true
  }

  /** Until the edits on their way and everything queued before them are done. */
  async function settled(): Promise<void> {
    sendDerive()
    await queue
  }

  /** The shown file's label in the group (`E11`), as the sources panel shows it. */
  function labelOf(sources: SourcesStore, groupId: string, sourceId: string): string {
    const item = panelItems(sources.entries, sources.grouping).find(
      (found) => found.kind === 'group' && found.group.id === groupId,
    )
    const rows = item?.kind === 'group' ? item.rows : []
    return rows.find((row) => row.entry.id === sourceId)?.label ?? ''
  }

  /**
   * Refuses (a toast) a track edit of the shown file when it is not an exact member and the
   * template has no explicit rules of that kind: the rules would be derived from this file
   * alone, and the other files would lose the tracks it lacks.
   */
  function refusedNear(state: GroupState, sections: Iterable<TemplateSection>): boolean {
    const template = state.document.template
    const derivesRules = [...sections].some(
      (section) =>
        (section === 'audio' && (template.audio_rules ?? []).length === 0) ||
        (section === 'subtitles' && (template.subtitle_rules ?? []).length === 0),
    )
    const found = group.value
    const sources = sourcesStore.value
    if (!derivesRules || found === null || sources === null) return false
    const path = sources.entries.find((entry) => entry.id === state.sourceId)?.path
    const member = found.members?.find((candidate) => candidate.path === path)
    if (member === undefined || member.match === 'exact') return false
    const file = labelOf(sources, state.groupId, state.sourceId)
    refuse(
      text('editor.group.nearMember', { file }),
      text('editor.group.nearMemberDetail', {
        file,
        representative: labelOf(sources, state.groupId, representativeOf(found, sources)),
      }),
    )
    return true
  }

  /** An edit of scope `group`: shown at once, derived into the template after a pause. */
  function patchGroup(current: GroupTarget, next: JobSettings, key: string | null): void {
    const field = perFileChange(current.job, next)
    if (field !== null) {
      refuse(
        text('editor.group.perFile', { field: text(`editor.group.fields.${field}`) }),
        text('editor.group.perFileDetail'),
      )
      return
    }
    const state = requireGroup('patch')
    const { sections, output } = sectionsOf(diffJson(current.job, next))
    if (refusedNear(state, sections)) return
    if (failedEdit !== null) {
      endEdit(failedEdit)
      failedEdit = null
    }
    // As for a job, an edit ends what there was to redo; its step comes with the derive.
    if (history.value.undone.length > 0) history.value = { ...history.value, undone: [] }
    if (waiting === null) {
      const edit: DeriveBatch['edit'] = reactive({
        flush: () => (edit.failure === null ? sendDerive() : endEdit(edit)),
        failure: null,
      })
      waiting = {
        state,
        job: next,
        sourceId: current.sourceId,
        sections: new Set(),
        output: false,
        key,
        endRun: false,
        dropped: false,
        edit,
      }
      beginEdit(edit)
    }
    for (const section of sections) waiting.sections.add(section)
    waiting.output ||= output
    waiting.job = next
    waiting.key = key
    target.value = { ...current, job: next }
    clearTimeout(deriveTimer)
    deriveTimer = setTimeout(sendDerive, EDIT_DEBOUNCE)
  }

  /** An edit of scope `file`: into the shown file's override, one undo step at once. */
  function patchFile(
    current: GroupTarget,
    ops: JsonPatchOp[],
    next: JobSettings,
    key: string | null,
  ): void {
    if (ops.some(changesTrackList)) {
      refuse(text('editor.group.trackListPerFile'), text('editor.group.trackListPerFileDetail'))
      return
    }
    const state = requireGroup('patch')
    const override = mergeOverride(
      state.document.overrides[current.sourceId] ?? [],
      ops.map(inJob),
      current.job,
    )
    commit(state, overriddenWith(state.document, current.sourceId, override), key)
    target.value = groupTarget(state, next)
  }

  /** The preset as a template, frozen. */
  async function presetTemplate(id: string): Promise<JobTemplate> {
    const preset =
      presets.byId(id) ??
      unwrap(await api.GET('/api/presets/{preset_id}', { params: { path: { preset_id: id } } }))
    return deepFreeze(cloneJson(templateOfPreset(preset)))
  }

  async function newState(
    found: BatchGroup,
    sources: SourcesStore,
    preset: string | null,
  ): Promise<GroupState> {
    if (preset === null) await presets.ensureLoaded()
    const id = preset ?? (presets.defaultId as string)
    return {
      groupId: found.id,
      representative: found.representative,
      members: memberPaths(found),
      document: { template: await presetTemplate(id), overrides: {}, presetId: id },
      sourceId: representativeOf(found, sources),
      scope: 'group',
      history: EMPTY_HISTORY,
      version: 0,
    }
  }

  /**
   * Edits the group: its last state when it was edited before in this page, else a template
   * from the editor's preset (else the default preset). The job that was open is closed.
   * Rejects with the `ApiError` of a failed request (already a toast).
   */
  async function editGroup(groupId: string): Promise<void> {
    const sources = await useSources()
    const found = sources.grouping?.groups?.find((candidate) => candidate.id === groupId)
    if (found === undefined) throw new Error(`editor.editGroup: no group ${groupId}`)
    if (editedState()?.groupId === groupId) return
    const preset = presetId.value
    await load(
      async () => {
        const state = groups.get(groupId) ?? (await newState(found, sources, preset))
        const version = state.version
        const sourceId = memberIdsOf(found, sources).includes(state.sourceId)
          ? state.sourceId
          : representativeOf(found, sources)
        const row = await resolved(api, state.document, sourceId, state.scope === 'file')
        return { state, version, sourceId, row }
      },
      ({ state, version, sourceId, row }) => {
        leaveGroup()
        const kept = groups.get(groupId) ?? state
        groups.set(groupId, kept)
        kept.sourceId = sourceId
        history.value = kept.history
        shownRow = row
        place(groupTarget(kept, row.job as JobSettings), draftOf(row), true)
        sources.activeId = sourceId
        if (kept !== state || kept.version !== version) shown.schedule(0)
        requestMatrix()
      },
    )
  }

  async function reshow(state: GroupState, sourceId: string, scope: GroupScope): Promise<void> {
    if (state.sourceId === sourceId && state.scope === scope) return
    await settled()
    await load(
      async () => {
        const version = state.version
        return { version, row: await resolved(api, state.document, sourceId, scope === 'file') }
      },
      ({ version, row }) => {
        if (editedState() !== state) return
        shown.cancel()
        state.sourceId = sourceId
        state.scope = scope
        shownRow = row
        place(groupTarget(state, row.job as JobSettings), draftOf(row), true)
        if (sourcesStore.value !== null) sourcesStore.value.activeId = sourceId
        if (state.version !== version) shown.schedule(0)
      },
    )
  }

  /** Shows another file of the group (the representative switcher). */
  async function showFile(sourceId: string): Promise<void> {
    const state = requireGroup('showFile')
    await reshow(state, sourceId, state.scope)
  }

  /** Where the next edits go. */
  async function setScope(scope: GroupScope): Promise<void> {
    const state = requireGroup('setScope')
    await reshow(state, state.sourceId, scope)
  }

  /**
   * A change of the group's template (a fix, the defaults dialog, a paste): one undo step, after
   * the edits and derives on their way. Ops that do not apply throw `PatchError` (or reject with
   * it, when the change waited).
   */
  function patchTemplate(ops: JsonPatchOp[], options?: PatchOptions): Promise<void> {
    const state = requireGroup('patchTemplate')
    const change = (): void => {
      const template = applyOps(state.document.template, ops)
      commit(state, { ...state.document, template }, options?.coalesce ?? null)
    }
    sendDerive()
    if (queued > 0) return enqueue(async () => change())
    change()
    return Promise.resolve()
  }

  /**
   * The derive's sections of its job into its state's template, with the job's output options
   * when `output`: one undo step with what `change` adds. A template changed while the derive
   * was on its way is derived again.
   */
  async function deriveInto(derive: Derive): Promise<void> {
    if (derive.dropped) return
    const { state } = derive
    const base = state.document.template
    let template = await derived(derive.job, derive.sourceId, [...derive.sections], base)
    if (derive.dropped) return
    if (state.document.template !== base) return deriveInto(derive)
    if (derive.output && derive.job.output !== undefined) {
      template = { ...template, output: outputOptionsOf(derive.job.output) }
    }
    const document = { ...state.document, template }
    commit(state, derive.change?.(document) ?? document, derive.key)
    if (derive.endRun) endRunOf(state)
  }

  /**
   * *Apply to group* and *Paste*: `batch/derive` of the `sections` of `from` (a job of
   * `sourceId`) into the template of the group `groupId` (edited now or before; else one from
   * the job's preset), one undo step of that group. Rejects as `editGroup`.
   */
  async function mergeIntoGroup(
    groupId: string,
    from: JobSettings,
    sourceId: string,
    sections: TemplateSection[],
  ): Promise<void> {
    let state = groups.get(groupId)
    if (state === undefined) {
      const sources = await useSources()
      const found = sources.grouping?.groups?.find((candidate) => candidate.id === groupId)
      if (found === undefined) throw new Error(`editor.mergeIntoGroup: no group ${groupId}`)
      const created = await newState(found, sources, from.preset_id ?? null)
      state = groups.get(groupId) ?? created
      groups.set(groupId, state)
    }
    const derive: Derive = {
      state,
      job: from,
      sourceId,
      sections: new Set(sections),
      output: false,
      key: null,
      endRun: false,
      dropped: false,
    }
    sendDerive()
    await enqueue(() => deriveInto(derive))
  }

  function changeOverride(sourceId: string, change: (ops: JsonPatchOp[]) => JsonPatchOp[]): void {
    const state = requireGroup('override')
    commit(
      state,
      overriddenWith(state.document, sourceId, change(state.document.overrides[sourceId] ?? [])),
    )
  }

  /**
   * A matrix cell picked by hand: rule `rule` of `kind` takes `stream` (an absolute stream
   * index) in this file, or no track (`null`). One undo step. Throws when the template has no
   * explicit rule there: a hand pick cannot change the rules the defaults compile to. The pick
   * is guarded by the rule's selector: once the template changes or moves that rule, the pick
   * is stale instead of taking a track for another rule.
   */
  function pickTrack(sourceId: string, kind: RuleKind, rule: number, stream: number | null): void {
    const template = requireGroup('pickTrack').document.template
    const found = (kind === 'audio' ? template.audio_rules : template.subtitle_rules)?.[rule]
    if (found === undefined) {
      throw new Error(`editor.pickTrack: the template has no explicit ${kind} rule ${rule}`)
    }
    const selector = `/${kind}_rules/${rule}/selector`
    const op: JsonPatchOp =
      stream === null
        ? { op: 'replace', path: `${selector}/languages`, value: [] }
        : { op: 'replace', path: `${selector}/stream`, value: stream }
    const guard = { op: 'test', path: selector, value: found.selector } as JsonPatchOp
    changeOverride(sourceId, (ops) =>
      ordered([...ops.filter((earlier) => !within(earlier.path, selector)), guard, op]),
    )
  }

  /** The cell back to the group's rule. One undo step. */
  function resetTrack(sourceId: string, kind: RuleKind, rule: number): void {
    const selector = `/${kind}_rules/${rule}/selector`
    changeOverride(sourceId, (ops) => withoutOps(ops, (op) => within(op.path, selector)))
  }

  /**
   * A parsed-name field of this file (`episode`, `sub_title`) corrected by hand; `null` takes
   * the parsed value again. One undo step.
   */
  function setNameField(sourceId: string, field: string, value: string | null): void {
    const path = `/job${pointerOf(`output.naming.field_overrides.${field}`)}`
    changeOverride(sourceId, (ops) => {
      const kept = withoutOps(ops, (op) => within(op.path, path))
      return value === null ? kept : ordered([...kept, { op: 'add', path, value }])
    })
  }

  /**
   * The range the shown file encodes: the job's. In a group it is the whole source with the
   * shown file's override (a template has no range), known before the shown job is resolved
   * again, and also in scope `group`, whose shown job leaves the override out.
   */
  const range = computed<Range>(() => {
    const current = target.value
    if (current === null) return FULL
    if (current.kind === 'job') return current.job.range ?? FULL
    try {
      return applyOps({ job: { range: FULL } }, rangeOps(current)).job.range
    } catch (error) {
      if (!(error instanceof PatchError)) throw error
      return current.job.range ?? FULL
    }
  })

  /** The edited group's shown file has a range of its own. */
  const rangeOverridden = computed(() => {
    const current = target.value
    return current?.kind === 'group' && rangeOps(current).length > 0
  })

  /** The shown file's range override becomes `next` (none for the whole source); one undo step. */
  function overrideRange(current: GroupTarget, value: Range): void {
    const state = requireGroup('setRange')
    const next = deepFreeze(cloneJson(value))
    changeOverride(current.sourceId, (ops) => {
      const kept = withoutOps(ops, (op) => within(op.path, FILE_RANGE))
      return next.kind === 'full'
        ? kept
        : ordered([...kept, { op: 'replace', path: FILE_RANGE, value: next }])
    })
    if (state.scope === 'file') {
      target.value = groupTarget(state, deepFreeze({ ...current.job, range: next }))
    }
  }

  /**
   * The range, one undo step. In a group, whatever the scope, it is the shown file's override:
   * a template has no range.
   */
  function setRange(next: Range): void {
    const current = target.value
    if (current === null) throw new Error('editor.setRange: no job is open')
    if (sameJson(next, range.value)) return
    if (current.kind === 'job') set('/range', next)
    else overrideRange(current, next)
  }

  /** The shown file encodes the whole source again, as the group does. One undo step. */
  function resetRangeToGroup(): void {
    const current = target.value
    if (current?.kind === 'group' && rangeOverridden.value) overrideRange(current, FULL)
  }

  /** A fix of one matrix row's issue: `template`, the group; `job`, that file; `settings`. */
  async function applyRowFix(sourceId: string, fix: Fix): Promise<void> {
    if (fix.target !== 'job') {
      await applyFix(fix)
      return
    }
    const state = requireGroup('applyRowFix')
    if (fix.patch.some(changesTrackList)) {
      refuse(text('editor.group.trackListPerFile'), text('editor.group.trackListPerFileDetail'))
      return
    }
    const row = await resolved(api, state.document, sourceId, true)
    changeOverride(sourceId, (ops) =>
      mergeOverride(ops, fix.patch.map(inJob), row.job as JobSettings),
    )
  }

  /** `path` (a validation path) is set per file: the template cannot hold it. */
  function perFile(path: string): boolean {
    return perFilePointer(pointerOf(path), job.value)
  }

  /** The edited group and the shown file's override, in scope `file`; `null` otherwise. */
  function shownOverride(): { state: GroupState; ops: JsonPatchOp[] } | null {
    const state = editedState()
    if (state === null || state.scope !== 'file') return null
    return { state, ops: state.document.overrides[state.sourceId] ?? [] }
  }

  /** Scope `file`: the shown file's override sets the value at `path` (`audio[1].bitrate`). */
  function overriddenAt(path: string): boolean {
    const current = target.value
    if (current?.kind !== 'group' || current.scope !== 'file') return false
    const pointer = `/job${pointerOf(path)}`
    const ops = current.overrides[current.sourceId] ?? []
    return ops.some((op) => op.op !== 'test' && related(op.path, pointer))
  }

  /** *Reset to group*: the shown file takes the group's value at `path` again. One undo step. */
  function resetToGroup(path: string): void {
    const found = shownOverride()
    if (found === null) return
    const pointer = `/job${pointerOf(path)}`
    changeOverride(found.state.sourceId, (ops) =>
      withoutOps(ops, (op) => related(op.path, pointer)),
    )
  }

  /**
   * *Apply to whole group*: the shown file's value at `path` goes into the template, as an edit
   * of scope `group` would put it, and leaves the override. One undo step.
   */
  async function applyToWholeGroup(path: string): Promise<void> {
    const found = shownOverride()
    if (found === null) return
    if (perFile(path)) {
      refuse(text('editor.group.notForGroup'), text('editor.group.notForGroupDetail'))
      return
    }
    const { state } = found
    const sourceId = state.sourceId
    const pointer = pointerOf(path)
    const value = get(pointer)
    await settled()
    const groupJob = (await resolved(api, state.document, sourceId, false)).job as JobSettings
    let from: JobSettings
    try {
      const op = hasPointer(groupJob, pointer) ? 'replace' : 'add'
      from = applyOps(groupJob, [{ op, path: pointer, value } as JsonPatchOp])
    } catch (error) {
      if (!(error instanceof PatchError)) throw error
      toast(text('editor.fixFailed'), text('editor.group.notForGroupDetail'))
      return
    }
    const { sections, output } = sectionsOf(diffJson(groupJob, from))
    if (refusedNear(state, sections)) return
    const inJobPointer = `/job${pointer}`
    const derive: Derive = {
      state,
      job: from,
      sourceId,
      sections: new Set(sections),
      output,
      key: null,
      endRun: false,
      dropped: false,
      change: (document) =>
        overriddenWith(
          document,
          sourceId,
          withoutOps(document.overrides[sourceId] ?? [], (op) => related(op.path, inJobPointer)),
        ),
    }
    await enqueue(() => deriveInto(derive))
  }

  /**
   * The group resolved now, after every edit on its way (a field's pending edit too): what
   * *Add group to queue* queues. Rejects with an `ApiError` and shows no toast: a failed
   * resolve (also `matrixError`), or an edit that could not reach the group.
   */
  async function resolveNow(): Promise<BatchResolution> {
    requireGroup('resolveNow')
    flushEdits()
    if (editing.value) {
      await new Promise<void>((resolve) => {
        // A field's edit that lands starts its derive: that one goes at once too.
        const stop = watch([pendingEdits, editing], () => {
          if (editing.value) {
            flushEdits()
            return
          }
          stop()
          resolve()
        })
      })
    }
    await settled()
    const failure = editFailure.value
    if (failure !== null) {
      const title = text('editor.group.editFailed')
      throw new ApiError(0, {
        type: 'about:blank',
        title,
        detail: failure,
        status: 0,
        code: 'edit.failed',
      })
    }
    return askMatrix()
  }

  /** The group that holds a state's representative now, else the most of its members. */
  function successorOf(state: GroupState, found: readonly BatchGroup[]): BatchGroup | undefined {
    const shared = (candidate: BatchGroup): number =>
      memberPaths(candidate).filter((path) => state.members.includes(path)).length
    return (
      found.find((candidate) => memberPaths(candidate).includes(state.representative)) ??
      found
        .filter((candidate) => shared(candidate) > 0)
        .toSorted((a, b) => shared(b) - shared(a))[0]
    )
  }

  // A group's id names its representative, so opening an earlier episode makes a new id: a
  // kept state follows its files. Synchronous, so the edited group never looks gone.
  watch(
    () => sourcesStore.value?.grouping?.groups,
    (found) => {
      if (found === undefined) return
      const edited = editedState()
      const gone = [...groups.values()]
        .filter((state) => !found.some((candidate) => candidate.id === state.groupId))
        .toSorted((a, b) => Number(b === edited) - Number(a === edited))
      for (const state of gone) {
        const next = successorOf(state, found)
        if (next === undefined || groups.has(next.id)) continue
        groups.delete(state.groupId)
        groups.set(next.id, state)
        state.groupId = next.id
        if (state === edited) target.value = { ...(target.value as GroupTarget), groupId: next.id }
      }
      for (const state of groups.values()) {
        const same = found.find((candidate) => candidate.id === state.groupId)
        if (same === undefined) continue
        state.representative = same.representative
        state.members = memberPaths(same)
      }
    },
    { flush: 'sync' },
  )

  // A member removed or added: the matrix again; the shown file gone: the representative; the
  // group gone: the editor closes.
  let watched: GroupState | null = null
  watch(
    () => (group.value === null ? null : `${group.value.id}\n${members.value.join('\n')}`),
    (now) => {
      const state = editedState()
      // Another group edited: `editGroup` has asked for its matrix.
      const same = state === watched
      watched = state
      if (state === null) return
      const sources = sourcesStore.value as SourcesStore
      if (now === null) {
        close()
        watched = null
        sources.activeId = null
        return
      }
      if (!same) return
      const found = group.value as BatchGroup
      if (!members.value.includes(state.sourceId)) {
        showFile(representativeOf(found, sources)).catch((error: unknown) => {
          if (!(error instanceof ApiError)) throw error
        })
        return
      }
      requestMatrix()
    },
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
    applyRemuxDraft,
    loadJob,
    get,
    patch,
    set,
    amend,
    endCoalescing,
    applyFix,
    undo,
    redo,
    close,
    beginEdit,
    endEdit,
    flushEdits,
    refreshPresetChanges,
    group,
    resolution,
    resolving,
    matrixError,
    retryMatrix,
    editGroup,
    showFile,
    setScope,
    patchTemplate,
    mergeIntoGroup,
    pickTrack,
    resetTrack,
    setNameField,
    range,
    rangeOverridden,
    setRange,
    resetRangeToGroup,
    applyRowFix,
    overriddenAt,
    resetToGroup,
    applyToWholeGroup,
    resolveNow,
    perFile,
  }
})
