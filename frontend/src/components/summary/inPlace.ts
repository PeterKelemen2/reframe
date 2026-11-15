import type { MediaSource, ValidationIssue } from '@/api/types'

/** Matroska and not WebM: the only files Reframe edits in place. */
export function isMatroska(source: MediaSource): boolean {
  const formats = (source.container?.format_name ?? '').split(',')
  return formats.includes('matroska') && !source.ref.path.toLowerCase().endsWith('.webm')
}

/** The `inplace.*` issues of an in-place edit. */
export function inPlaceIssues(issues: readonly ValidationIssue[]): ValidationIssue[] {
  return issues.filter((issue) => issue.code.startsWith('inplace.'))
}
