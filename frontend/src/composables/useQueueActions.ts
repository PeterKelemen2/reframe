import { type ComputedRef, computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, QueueJob, SourceEntry, ValidationIssue } from '@/api/types'
import { fileName } from '@/components/shell/format'
import { useEditorStore } from '@/stores/editor'
import { useQueueStore } from '@/stores/queue'
import { useSourcesStore } from '@/stores/sources'
import { useToastStore } from '@/stores/toasts'
import { useValidationStore } from '@/stores/validation'

export interface QueueActions {
  /** The editor's job has no error, and nothing is in the way of adding it. */
  canAdd: ComputedRef<boolean>
  /** At least one source is open and no add is under way. */
  canAddAll: ComputedRef<boolean>
  /** Waiting jobs that a Start would hand to the runner. */
  canStart: ComputedRef<boolean>
  /** Adds the editor's job (`Ctrl+Enter`, *Add to queue*). */
  addCurrent(): Promise<void>
  /** Drafts every open source with the editor's preset and adds those without errors. */
  addAll(): Promise<void>
  /** Starts the queue. */
  start(): Promise<void>
}

type Outcome = { entry: SourceEntry; job: JobSettings } | { entry: SourceEntry; reason: string }

const ADDED_LIFE = 4_000
const NOT_ADDED_LIFE = 15_000

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

  const canAdd = computed(
    () =>
      editor.job !== null &&
      !editor.loading &&
      !validation.pending &&
      !validation.hasErrors &&
      Boolean(editor.job.output?.path) &&
      !busy.value,
  )
  const canAddAll = computed(() => sources.entries.length > 0 && !busy.value)
  const canStart = computed(
    () => queue.counts.waiting > 0 && !(queue.processing && queue.only === null),
  )

  async function addCurrent(): Promise<void> {
    const job = editor.job
    if (!canAdd.value || job === null) return
    busy.value = true
    try {
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
      if (validation.pending || editor.loading) {
        return { entry, reason: t('shell.queue.stillChecking') }
      }
      const error = firstError(validation.issues)
      if (error) return { entry, reason: error.message }
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

  return { canAdd, canAddAll, canStart, addCurrent, addAll, start }
}
