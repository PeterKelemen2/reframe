import { type ComputedRef, computed, ref, shallowRef } from 'vue'

import { ApiError } from '@/api/client'
import { text } from '@/api/text'
import type { JobSettings } from '@/api/types'
import { rowLabels } from '@/components/matrix/matrix'
import { fileName } from '@/components/shell/format'
import { commitFocusedField } from '@/editor/focus'
import { useEditorStore } from '@/stores/editor'
import { useQueueStore } from '@/stores/queue'
import { useSourcesStore } from '@/stores/sources'
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
}

export type GroupAnswer = 'valid' | 'matrix' | 'cancel'

export interface QueueGroup {
  /** A group is being resolved or queued. */
  busy: ComputedRef<boolean>
  /**
   * *Add group to queue*: edits the group `groupId` when it is not the edited one, resolves it,
   * and queues one job per file in episode order; when files have errors, asks first (queue the
   * valid files, open the matrix, or cancel).
   */
  queueGroup(groupId: string): Promise<void>
  /** The question that waits for an answer. */
  question: ComputedRef<GroupQuestion | null>
  answer(choice: GroupAnswer): void
}

const ADDED_LIFE = 4_000
const NOT_ADDED_LIFE = 15_000

// Shared by every caller (the group row, the banner, the status bar, the shortcut), so that a
// second click during a queueing does not queue the group twice.
const busy = ref(false)
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

/** Uses stores only, so a click handler may call it outside a component's setup. */
export function useQueueGroup(): QueueGroup {
  const editor = useEditorStore()
  const queue = useQueueStore()
  const sources = useSourcesStore()
  const toasts = useToastStore()
  const ui = useUiStore()

  async function queueGroup(groupId: string): Promise<void> {
    if (busy.value) return
    busy.value = true
    try {
      commitFocusedField()
      const target = editor.target
      if (target?.kind !== 'group' || target.groupId !== groupId) await editor.editGroup(groupId)
      const resolution = await editor.resolveNow()
      let rows = resolution.rows ?? []
      const failed = rows.filter((row) => row.status === 'error')
      if (failed.length > 0) {
        const labels = rowLabels(failed, resolution.group?.members ?? [])
        const files = failed.map((row, index) => ({
          sourceId: sources.entries.find((entry) => entry.path === row.path)?.id ?? null,
          label: labels[index] ?? fileName(row.path),
          message: row.issues?.find((issue) => issue.severity === 'error')?.message ?? '',
        }))
        const choice = await ask({ failed: files, valid: rows.length - failed.length })
        if (choice === 'cancel') return
        if (choice === 'matrix') {
          ui.openMatrix(files[0]?.sourceId ?? null)
          return
        }
        rows = rows.filter((row) => row.status !== 'error')
      }
      const jobs = rows.flatMap((row): JobSettings[] => (row.job ? [row.job] : []))
      if (jobs.length === 0) return
      const added = await queue.add(jobs)
      const accepted = added.filter((job) => job.state !== 'failed').length
      if (accepted > 0) {
        toasts.push({
          severity: 'success',
          summary: text('matrix.queue.queued', { n: accepted }),
          life: ADDED_LIFE,
        })
      }
      const refused = added.filter((job) => job.state === 'failed')
      if (refused.length > 0) {
        toasts.push({
          severity: 'warn',
          summary: text('matrix.queue.notQueued', { n: refused.length }),
          detail: refused
            .map((job) =>
              text('matrix.queue.notQueuedLine', {
                name: fileName(job.settings.source.path),
                reason: job.error ?? text('matrix.queue.failed'),
              }),
            )
            .join('\n'),
          life: NOT_ADDED_LIFE,
        })
      }
    } catch (error) {
      // The API client has shown the problem as a toast.
      if (!(error instanceof ApiError)) throw error
    } finally {
      busy.value = false
    }
  }

  return {
    busy: computed(() => busy.value),
    queueGroup,
    question: computed(() => question.value),
    answer,
  }
}
