import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ValidationIssue } from '@/api/types'
import { formatDuration } from '@/components/shell/format'
import { useJobSource } from '@/components/summary/useJobSource'
import { useEditorStore } from '@/stores/editor'
import { useValidationStore } from '@/stores/validation'

import { rangeLabel, rangeSeconds } from './range'

/** The paths of the range's issues. */
export const RANGE_PATHS = ['range', 'range.start', 'range.end'] as const
export type RangePath = (typeof RANGE_PATHS)[number]

/** The editor's range as the header and the Summary show it: its text, its length, its issues. */
export function useRange() {
  const editor = useEditorStore()
  const validation = useValidationStore()
  const { t } = useI18n()
  const { entry, source } = useJobSource()

  const range = computed(() => editor.range)
  const seconds = computed(() => rangeSeconds({ range: range.value }, source.value))
  const label = computed(() => rangeLabel(range.value, t))
  const length = computed(() => formatDuration(seconds.value))

  // In scope `group` the shown job leaves out the file's override, so the validation never sees
  // the file's range: the matrix row of the file has its issues.
  const fromRow = computed<ValidationIssue[] | null>(() => {
    const current = editor.target
    if (current?.kind !== 'group' || current.scope === 'file' || !editor.rangeOverridden) {
      return null
    }
    const row = editor.resolution?.rows?.find((found) => found.path === entry.value?.path)
    return row?.issues ?? []
  })

  function issuesAt(path: RangePath): ValidationIssue[] {
    const issues = fromRow.value
    if (issues === null) return validation.issuesFor(path)
    return issues.filter((issue) => issue.path === path)
  }

  const issues = computed(() => RANGE_PATHS.flatMap((path) => issuesAt(path)))

  return { range, source, seconds, label, length, issues, issuesAt }
}
