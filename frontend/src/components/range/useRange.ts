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
  const { t, n } = useI18n()
  const { source } = useJobSource()

  const range = computed(() => editor.range)
  const seconds = computed(() => rangeSeconds({ range: range.value }, source.value))
  const label = computed(() => rangeLabel(range.value, t, (value) => n(value)))
  const length = computed(() => formatDuration(seconds.value))

  function issuesAt(path: RangePath): ValidationIssue[] {
    return validation.issuesFor(path)
  }

  const issues = computed(() => RANGE_PATHS.flatMap((path) => issuesAt(path)))

  return { range, source, seconds, label, length, issues, issuesAt }
}
