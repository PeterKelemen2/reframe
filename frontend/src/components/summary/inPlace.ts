import type { MediaSource, ValidationIssue } from '@/api/types'

/** Matroska and not WebM: the only files mkvpropedit can edit in place. */
export function isMatroska(source: MediaSource): boolean {
  const formats = (source.container?.format_name ?? '').split(',')
  return formats.includes('matroska') && !source.ref.path.toLowerCase().endsWith('.webm')
}

/** The issues of an in-place edit: the `inplace.*` ones and any other at the switch. */
export function inPlaceIssues(issues: readonly ValidationIssue[]): ValidationIssue[] {
  return issues.filter(
    (issue) => issue.code.startsWith('inplace.') || issue.path === 'output.edit_in_place',
  )
}
