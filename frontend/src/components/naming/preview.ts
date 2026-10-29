import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { NameResult, Schemas, ValidationIssue } from '@/api/types'

import { TEMPLATE_PATH } from './fields'

export type NamingPreviewRequest = Schemas['NamingPreviewRequest']

/** Milliseconds from the last change to `naming/preview`. */
export const PREVIEW_DEBOUNCE = 250

/** `POST /api/naming/preview`; a failure rejects with `ApiError` and is not toasted. */
export async function previewNames(
  body: NamingPreviewRequest,
  signal: AbortSignal,
): Promise<NameResult[]> {
  return unwrap(await apiQuiet.POST('/api/naming/preview', { body, signal }))
}

/** The server's reason for a failed preview, or `null` when it gave none. */
export function failureText(error: unknown): string | null {
  if (error instanceof ApiError) return error.problem.detail ?? error.problem.title
  return null
}

/** Issues of the template, once each (several sources report the same ones). */
export function templateIssues(results: NameResult[]): ValidationIssue[] {
  return unique(results.flatMap((result) => result.issues ?? []).filter(isTemplateIssue))
}

export function isTemplateIssue(issue: ValidationIssue): boolean {
  return issue.path === TEMPLATE_PATH
}

export function unique(issues: ValidationIssue[]): ValidationIssue[] {
  const seen = new Set<string>()
  return issues.filter((issue) => {
    const key = `${issue.code}\n${issue.path}\n${issue.message}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** The whole template a template issue's fix puts in place ("Use {main_title}"), or `null`. */
export function fixedTemplate(fix: Schemas['Fix']): string | null {
  const op = fix.patch[0]
  if (fix.patch.length !== 1 || op === undefined || !('value' in op)) return null
  return typeof op.value === 'string' ? op.value : null
}
