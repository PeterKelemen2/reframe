import { type ComputedRef, computed, nextTick, ref, shallowRef } from 'vue'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type { BatchResolution, JobSettings, QueueJob, Resolution } from '@/api/types'
import { rowLabels } from '@/components/matrix/matrix'
import { fileName } from '@/components/shell/format'
import { commitFocusedField } from '@/editor/focus'
import { DETECTION_CANCELLED, useEditorStore } from '@/stores/editor'
import { useQueueStore } from '@/stores/queue'
import { useSourcesStore } from '@/stores/sources'
import { useTasksStore } from '@/stores/tasks'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

/** A file of the group that cannot be queued as it is. */
export interface FailedFile {
  /** `null` when the file is no longer open. */
  sourceId: string | null
  label: string
  /** Its first error. */
  message: string
}

/** What *Add group to queue* asks when files have errors. */
export interface GroupQuestion {
  failed: FailedFile[]
  /** Files without errors, which *Queue the valid files* queues. */
  valid: number
  /** Valid files with a stale override: they are queued without part of it. */
  stale: number
}

export type GroupAnswer = 'valid' | 'matrix' | 'cancel'

/** The crop detection that runs before a group is queued. */
export interface GroupDetection {
  /** What it does now: the file it measures, once it measures one. */
  message: string
}

export interface QueueGroup {
  /** A group is being resolved or queued. */
  busy: ComputedRef<boolean>
  /**
   * *Add group to queue*: edits the group `groupId` when it is not the edited one, resolves it
   * with each file's crop detected, and queues one job per file in episode order; when files
   * have errors, asks first (queue the valid files, open the matrix, or cancel).
   */
  queueGroup(groupId: string): Promise<void>
  /**
   * Queues one file of the edited group, resolved with its crop detected as `queueGroup` does;
   * a file with errors is a toast that says why.
   */
  queueFile(sourceId: string): Promise<void>
  /** The crop detection of the group being queued; `null` when none runs. */
  detection: ComputedRef<GroupDetection | null>
  /** Stops the crop detection: the group is not queued. */
  cancelDetection(): Promise<void>
  /** The question that waits for an answer. */
  question: ComputedRef<GroupQuestion | null>
  answer(choice: GroupAnswer): void
}

const ADDED_LIFE = 4_000
const NOT_ADDED_LIFE = 15_000
const PROBLEM_LIFE = 10_000
/** A second *Add group to queue* fails every job: the toast must still fit on the screen. */
const FAILED_LINES = 3

// Shared by every caller (the context menu, the status bar, the shortcut), so that a second click
// during a queueing does not queue the group twice.
const busy = ref(false)
const detectionTask = ref<string | null>(null)
let detectionCancelled = false
const question = shallowRef<GroupQuestion | null>(null)
let reply: ((choice: GroupAnswer) => void) | null = null

function ask(asked: GroupQuestion): Promise<GroupAnswer> {
  question.value = asked
  return new Promise((resolve) => (reply = resolve))
}

function answer(choice: GroupAnswer): void {
  const answered = reply
  question.value = null
  reply = null
  answered?.(choice)
}

function staleCount(rows: Resolution[]): number {
  return rows.filter((row) => row.issues?.some((issue) => issue.code === 'batch.override_stale'))
    .length
}

/** Each row whose crop could not be detected, with the issue that says why. */
function uncropped(rows: Resolution[]): { row: Resolution; message: string }[] {
  return rows.flatMap((row) => {
    const issue = row.issues?.find((found) => found.code === 'batch.crop_not_detected')
    return issue ? [{ row, message: issue.message }] : []
  })
}

/** Uses stores only, so a click handler may call it outside a component's setup. */
export function useQueueGroup(): QueueGroup {
  const editor = useEditorStore()
  const queue = useQueueStore()
  const sources = useSourcesStore()
  const tasks = useTasksStore()
  const toasts = useToastStore()
  const ui = useUiStore()

  /** The group's files that changed on disk since they were probed (listed without a source). */
  async function changedFiles(): Promise<string[]> {
    const members = new Set((editor.group?.members ?? []).map((member) => member.path))
    try {
      return unwrap(await apiQuiet.GET('/api/sources'))
        .filter((entry) => entry.source === null && members.has(entry.path))
        .map((entry) => fileName(entry.path))
    } catch (error) {
      if (!(error instanceof ApiError)) throw error
      return []
    }
  }

  async function showProblem(error: ApiError): Promise<void> {
    // The failed edit has shown its own toast.
    if (error.problem.code === 'edit.failed') return
    const changed = error.problem.code === 'source.stale' ? await changedFiles() : []
    const n = changed.length
    toasts.push(
      n > 0
        ? {
            severity: 'error',
            summary: text('matrix.queue.changed', { n }),
            detail: [text('matrix.queue.changedHelp', { n }), ...changed].join('\n'),
            life: PROBLEM_LIFE,
          }
        : {
            severity: 'error',
            summary: error.problem.title,
            detail: error.problem.detail ?? undefined,
            life: PROBLEM_LIFE,
          },
    )
  }

  /** One toast of what the queue did with the jobs of `rows`. */
  function reportAdded(rows: Resolution[], added: QueueJob[]): void {
    const failed = added.filter((job) => job.state === 'failed')
    const stale = staleCount(rows)
    const notCropped = uncropped(rows)
    const lines = [
      ...(stale > 0 ? [text('matrix.queue.stale', { n: stale })] : []),
      ...failed.slice(0, FAILED_LINES).map((job) =>
        text('matrix.queue.failedLine', {
          name: fileName(job.settings.source.path),
          reason: job.error ?? text('matrix.queue.failed'),
        }),
      ),
      ...(failed.length > FAILED_LINES
        ? [text('matrix.queue.moreFailed', { n: failed.length - FAILED_LINES })]
        : []),
      ...notCropped
        .slice(0, FAILED_LINES)
        .map(({ row, message }) =>
          text('matrix.queue.failedLine', { name: fileName(row.path), reason: message }),
        ),
      ...(notCropped.length > FAILED_LINES
        ? [text('matrix.queue.moreUncropped', { n: notCropped.length - FAILED_LINES })]
        : []),
    ]
    let summary = text('matrix.queue.queued', { n: added.length })
    if (failed.length > 0) {
      summary = text('matrix.queue.addedFailed', { n: added.length, failed: failed.length })
    } else if (notCropped.length > 0) {
      summary = text('matrix.queue.queuedUncropped', {
        n: added.length,
        uncropped: notCropped.length,
      })
    }
    toasts.push({
      severity: lines.length > 0 ? 'warn' : 'success',
      summary,
      detail: lines.length > 0 ? lines.join('\n') : undefined,
      life: lines.length > 0 ? NOT_ADDED_LIFE : ADDED_LIFE,
    })
  }

  async function queueGroup(groupId: string): Promise<void> {
    if (busy.value) return
    busy.value = true
    // The dialog gives the focus back to what had it when it opened, which may be the page.
    const opener = document.activeElement
    let choice: GroupAnswer | null = null
    detectionCancelled = false
    try {
      commitFocusedField()
      const target = editor.target
      if (target?.kind !== 'group' || target.groupId !== groupId) await editor.editGroup(groupId)
      let resolution: BatchResolution
      try {
        // Queueing detects each file's crop: the matrix shown while editing does not.
        resolution = await editor.resolveNow({
          detectCrop: true,
          onTask: (taskId) => (detectionTask.value = taskId),
        })
      } catch (error) {
        // `resolveNow` shows no toast of its own.
        if (!(error instanceof ApiError)) throw error
        if (error.problem.code !== DETECTION_CANCELLED) await showProblem(error)
        return
      } finally {
        detectionTask.value = null
      }
      // A Cancel that came as the task ended (the server had nothing left to cancel).
      if (detectionCancelled) return
      let rows = resolution.rows ?? []
      const failed = rows.filter((row) => row.status === 'error')
      if (failed.length > 0) {
        const labels = rowLabels(failed, resolution.group?.members ?? [])
        const files = failed.map((row, index) => ({
          sourceId: sources.entries.find((entry) => entry.path === row.path)?.id ?? null,
          label: labels[index] ?? fileName(row.path),
          message: row.issues?.find((issue) => issue.severity === 'error')?.message ?? '',
        }))
        rows = rows.filter((row) => row.status !== 'error')
        choice = await ask({ failed: files, valid: rows.length, stale: staleCount(rows) })
        if (choice === 'cancel') return
        if (choice === 'matrix') {
          ui.openMatrix(files[0]?.sourceId ?? null)
          return
        }
      }
      const jobs = rows.flatMap((row): JobSettings[] => (row.job ? [row.job] : []))
      if (jobs.length === 0) return
      reportAdded(rows, await queue.add(jobs))
    } catch (error) {
      // The API client has shown the problem as a toast.
      if (!(error instanceof ApiError)) throw error
    } finally {
      busy.value = false
      if (choice !== null && choice !== 'matrix' && opener instanceof HTMLElement) {
        await nextTick()
        opener.focus()
      }
    }
  }

  async function queueFile(sourceId: string): Promise<void> {
    if (busy.value || editor.target?.kind !== 'group') return
    busy.value = true
    detectionCancelled = false
    try {
      commitFocusedField()
      let resolution: BatchResolution
      try {
        resolution = await editor.resolveNow({
          detectCrop: true,
          only: sourceId,
          onTask: (taskId) => (detectionTask.value = taskId),
        })
      } catch (error) {
        if (!(error instanceof ApiError)) throw error
        if (error.problem.code !== DETECTION_CANCELLED) await showProblem(error)
        return
      } finally {
        detectionTask.value = null
      }
      if (detectionCancelled) return
      const [row] = resolution.rows ?? []
      if (row === undefined) return
      if (row.status === 'error' || !row.job) {
        toasts.push({
          severity: 'warn',
          summary: text('editor.add.hasErrors'),
          detail: row.issues?.find((issue) => issue.severity === 'error')?.message,
          life: NOT_ADDED_LIFE,
        })
        return
      }
      reportAdded([row], await queue.add([row.job]))
    } catch (error) {
      // The API client has shown the problem as a toast.
      if (!(error instanceof ApiError)) throw error
    } finally {
      busy.value = false
    }
  }

  const detection = computed<GroupDetection | null>(() => {
    const taskId = detectionTask.value
    if (taskId === null) return null
    const task = tasks.tasks[taskId]
    // Before its first file the task's message names no file.
    const measuring = task?.progress != null ? task.message : null
    return { message: measuring || text('group.banner.detecting') }
  })

  async function cancelDetection(): Promise<void> {
    const taskId = detectionTask.value
    if (taskId === null) return
    detectionCancelled = true
    try {
      await tasks.cancel(taskId)
    } catch (error) {
      // The API client has shown the problem as a toast.
      if (!(error instanceof ApiError)) throw error
    }
  }

  return {
    busy: computed(() => busy.value),
    queueGroup,
    queueFile,
    detection,
    cancelDetection,
    question: computed(() => question.value),
    answer,
  }
}
