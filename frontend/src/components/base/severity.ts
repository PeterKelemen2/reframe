import { CircleX, Info, TriangleAlert } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import type { Severity, ValidationIssue } from '@/api/types'

const ORDER: Record<Severity, number> = { error: 0, warning: 1, info: 2 }

/** Most severe first; issues of one severity keep their order. */
export function bySeverity(issues: readonly ValidationIssue[]): ValidationIssue[] {
  return issues.toSorted((a, b) => ORDER[a.severity] - ORDER[b.severity])
}

/** The icon that goes with a severity; the colour comes from the `--p-status-*` tokens. */
export const SEVERITY_ICON = { error: CircleX, warning: TriangleAlert, info: Info } as const

/** The severity's name for screen readers (the icon and colour show it to the eye). */
export function useSeverityLabel(): (severity: Severity) => string {
  const { t } = useI18n()
  return (severity) => {
    switch (severity) {
      case 'error':
        return t('base.severity.error')
      case 'warning':
        return t('base.severity.warning')
      case 'info':
        return t('base.severity.info')
    }
  }
}
