import { type ComputedRef, computed, ref, watch, type WatchStopHandle } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, QueueJob, SourceEntry, ValidationIssue } from '@/api/types'
import { fileName } from '@/components/shell/format'
import { commitFocusedField } from '@/editor/focus'
import { useEditorStore } from '@/stores/editor'
import { useQueueStore } from '@/stores/queue'
import { useSourcesStore } from '@/stores/sources'
import { useToastStore } from '@/stores/toasts'
import { useValidationStore } from '@/stores/validation'

export interface QueueActions {
  /**
   * The editor's job had no error at its last check, and nothing is in the way of adding it. A
   * check or an edit on its way does not count: the add waits for them.
   */
  canAdd: ComputedRef<boolean>
  /** At least one source is open and no add is under way. */
  canAddAll: ComputedRef<boolean>
  /** Waiting jobs that a Start would hand to the runner. */
  canStart: ComputedRef<boolean>
  /** An add is under way (it may still wait for the job's check). */
  busy: ComputedRef<boolean>
  /**
   * Adds the editor's job as the screen shows it (`Ctrl+Enter`, *Add to queue*): first the
   * focused field's value and the edits on their way go into the job and the job is checked.
   * A job that cannot be added then is a toast that says why.
   */
  addCurrent(): Promise<void>
  /** Drafts every open source with the editor's preset and adds those without errors. */
  addAll(): Promise<void>
  /** Starts the queue. */
  start(): Promise<void>
}

type Outcome = { entry: SourceEntry; job: JobSettings } | { entry: SourceEntry; reason: string }

/** Why the open job cannot be added now. */
type Blocker =
  | { kind: 'checking' }
  | { kind: 'unchecked' }
  | { kind: 'edit'; reason: string }
  | { kind: 'error'; message: string }
  | { kind: 'noPath' }

const ADDED_LIFE = 4_000
const NOT_ADDED_LIFE = 15_000
/** An add that waits longer for the job's check gives up (a server that does not answer). */
const SETTLE_LIMIT = 20_000

// Shared by every caller (the status bar's buttons and the shortcut), so that a second click or
// a held Ctrl+Enter during an add does not queue the job twice.
const busy = ref(false)

/** The request body is read later than the click; a copy keeps edits made meanwhile out of it. */
function snapshot(job: JobSettings): JobSettings {
  return JSON.parse(JSON.stringify(job)) as JobSettings
}

function firstError(issues: readonly ValidationIssue[] | undefined): ValidationIssue | undefined {
  return issues?.find((issue) => issue.severity === 'error')
}

/** The API client has already shown the problem as a toast. */
function shown(error: unknown): void {
  if (!(error instanceof ApiError)) throw error
}

/** The status bar's queue actions; the shortcut uses `addCurrent` too. */
export function useQueueActions(): QueueActions {
  const { t } = useI18n()
  const editor = useEditorStore()
  const validation = useValidationStore()
  const queue = useQueueStore()
  const sources = useSourcesStore()
  const toasts = useToastStore()

  // A check or an edit on its way does not turn it off: a click on the button blurs the field
  // that was typed in, its value goes into the job, and the button must stay enabled under the
  // pointer. The add waits for them.
  const canAdd = computed(
    () =>
      editor.job !== null &&
      !editor.loading &&
      !validation.hasErrors &&
      Boolean(editor.job.output?.path) &&
      !busy.value,
  )
  const canAddAll = computed(() => sources.entries.length > 0 && !busy.value)
  const canStart = computed(
    () => queue.counts.waiting > 0 && !(queue.processing && queue.only === null),
  )

  /**
   * Resolves once what the screen shows is in the job and the job has been checked, or after
   * `SETTLE_LIMIT`: `false` when another job was opened meanwhile. A failed check is asked once
   * more.
   */
  function settled(): Promise<boolean> {
    commitFocusedField()
    editor.flushEdits()
    const session = editor.session
    let retried = false
    return new Promise((resolve) => {
      let stop: WatchStopHandle | undefined
      let over = false
      const limit = setTimeout(() => finish(true), SETTLE_LIMIT)
      function finish(value: boolean): void {
        if (over) return
        over = true
        clearTimeout(limit)
        stop?.()
        resolve(value)
      }
      // Not `sync`: an edit that lands makes the check pending in the same change, and that
      // must be seen together.
      stop = watch(
        () =>
          [
            editor.session,
            editor.loading,
            editor.editing,
            validation.pending,
            validation.failed,
          ] as const,
        () => {
          if (over) return
          if (editor.session !== session) return finish(false)
          if (editor.loading || editor.editing) return
          if (validation.pending) {
            validation.flush()
            return
          }
          if (validation.failed && !retried) {
            retried = true
            validation.flush()
            return
          }
          finish(true)
        },
        { immediate: true },
      )
      if (over) stop()
    })
  }

  /** Why the open job cannot be added as it is now; `null`: it can. */
  function blocker(job: JobSettings): Blocker | null {
    if (editor.loading || editor.editing || validation.pending) return { kind: 'checking' }
    if (editor.editFailure !== null) return { kind: 'edit', reason: editor.editFailure }
    if (validation.failed) return { kind: 'unchecked' }
    const error = firstError(validation.issues)
    if (error) return { kind: 'error', message: error.message }
    if (!job.output?.path) return { kind: 'noPath' }
    return null
  }

  /** A line of *Add all*'s list: "name: reason". */
  function lineReason(found: Blocker): string {
    switch (found.kind) {
      case 'checking':
        return t('shell.queue.stillChecking')
      case 'unchecked':
        return t('editor.add.uncheckedLine')
      case 'edit':
        return t('editor.add.editLine', { reason: found.reason })
      case 'error':
        return found.message
      case 'noPath':
        return t('shell.queue.noOutputPath')
    }
  }

  function toastReason(found: Blocker): string {
    switch (found.kind) {
      case 'checking':
        return t('editor.add.checking')
      case 'unchecked':
        return t('editor.add.unchecked')
      case 'edit':
        return t('editor.add.edit', { reason: found.reason })
      case 'error':
        return found.message
      case 'noPath':
        return t('editor.add.noPath')
    }
  }

  async function addCurrent(): Promise<void> {
    if (busy.value || editor.job === null || editor.loading) return
    busy.value = true
    try {
      if (!(await settled())) return
      const job = editor.job
      if (job === null) return
      const found = blocker(job)
      if (found !== null) {
        toasts.push({
          severity: 'warn',
          summary: t(found.kind === 'error' ? 'editor.add.hasErrors' : 'editor.add.notAdded'),
          detail: toastReason(found),
          life: NOT_ADDED_LIFE,
        })
        return
      }
      const [added] = await queue.add([snapshot(job)])
      if (added?.state === 'failed') {
        toasts.push({
          severity: 'error',
          summary: t('shell.queue.addFailed'),
          detail: added.error ?? undefined,
        })
      } else {
        toasts.push({
          severity: 'success',
          summary: t('shell.queue.added'),
          detail: fileName(job.output?.path ?? ''),
          life: ADDED_LIFE,
        })
      }
    } catch (error) {
      shown(error)
    } finally {
      busy.value = false
    }
  }

  /** The open job as the editor has it (with the user's edits); every other source drafted. */
  async function jobOf(entry: SourceEntry): Promise<Outcome> {
    const target = editor.target
    let job: JobSettings
    if (target?.kind === 'job' && target.sourceId === entry.id && editor.job !== null) {
      const found = blocker(editor.job)
      if (found !== null) return { entry, reason: lineReason(found) }
      job = editor.job
    } else {
      try {
        const draft = unwrap(
          await apiQuiet.POST('/api/jobs/draft', {
            body: { source_id: entry.id, preset_id: editor.presetId },
          }),
        )
        const error = firstError(draft.issues)
        if (error) return { entry, reason: error.message }
        job = draft.job
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
        return { entry, reason: error.problem.title }
      }
    }
    if (!job.output?.path) return { entry, reason: t('shell.queue.noOutputPath') }
    return { entry, job: snapshot(job) }
  }

  async function addAll(): Promise<void> {
    if (!canAddAll.value) return
    busy.value = true
    try {
      await settled()
      const outcomes = await Promise.all(sources.entries.map((entry) => jobOf(entry)))
      const ready = outcomes.filter((outcome) => 'job' in outcome)
      const lines = outcomes.flatMap((outcome) =>
        'reason' in outcome
          ? [
              t('shell.queue.notAddedLine', {
                name: fileName(outcome.entry.path),
                reason: outcome.reason,
              }),
            ]
          : [],
      )
      let added: QueueJob[] = []
      if (ready.length > 0) {
        try {
          added = await queue.add(ready.map((outcome) => outcome.job))
        } catch (error) {
          shown(error)
          return
        }
      }
      for (const job of added) {
        if (job.state !== 'failed') continue
        lines.push(
          t('shell.queue.notAddedLine', {
            name: fileName(job.settings.source.path),
            reason: job.error ?? t('shell.queue.addFailed'),
          }),
        )
      }
      const accepted = added.filter((job) => job.state !== 'failed').length
      if (accepted > 0) {
        toasts.push({
          severity: 'success',
          summary: t('shell.queue.addedAll', accepted),
          life: ADDED_LIFE,
        })
      }
      if (lines.length > 0) {
        toasts.push({
          severity: 'warn',
          summary: t('shell.queue.notAdded', lines.length),
          detail: lines.join('\n'),
          life: NOT_ADDED_LIFE,
        })
      }
    } finally {
      busy.value = false
    }
  }

  async function start(): Promise<void> {
    try {
      await queue.start()
    } catch (error) {
      shown(error)
    }
  }

  return {
    canAdd,
    canAddAll,
    canStart,
    busy: computed(() => busy.value),
    addCurrent,
    addAll,
    start,
  }
}
