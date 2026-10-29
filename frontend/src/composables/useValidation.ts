import { getCurrentScope, onScopeDispose, watch } from 'vue'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { JobDraft, JobSettings, ValidationIssue } from '@/api/types'
import { latestRequest } from '@/editor/latest'
import { sameJson } from '@/editor/patch'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useValidationStore } from '@/stores/validation'

/**
 * Issues of the draft that `jobs/validate` never gives: how the preset's track rules and
 * defaults met the source, and an unknown preset. Their paths are in the preset.
 */
function draftOnly(issue: ValidationIssue): boolean {
  return /^(batch|defaults|preset)\./.test(issue.code)
}

/** The job editor applies fixes to the job and the settings; a template fix needs a group. */
function forJob(issues: readonly ValidationIssue[]): ValidationIssue[] {
  return issues.map((issue) =>
    issue.fixes?.some((fix) => fix.target === 'template')
      ? { ...issue, fixes: issue.fixes.filter((fix) => fix.target !== 'template') }
      : issue,
  )
}

/** The draft's own issues, while the job is still the drafted one. */
function draftIssues(draft: JobDraft | null, job: JobSettings): ValidationIssue[] {
  if (draft === null || !sameJson(draft.job, job)) return []
  return (draft.issues ?? []).filter(draftOnly)
}

/** The path of a request field: `['body', 'job', 'video', 'rate_control', 'quality', 'value']`. */
function requestPath(loc: readonly (string | number)[], job: JobSettings): string | null {
  if (loc[0] !== 'body' || loc[1] !== 'job') return null
  let node: unknown = job
  let path = ''
  const parts = loc.slice(2)
  for (const [index, part] of parts.entries()) {
    const key = String(part)
    const member = typeof node === 'object' && node !== null && Object.hasOwn(node, key)
    // Not in the job: the tag of a union member (`quality`), or a missing field when it is last.
    if (!member && index < parts.length - 1) continue
    node = member ? (node as Record<string, unknown>)[key] : undefined
    path += typeof part === 'number' ? `[${part}]` : path === '' ? key : `.${key}`
  }
  return path
}

/** A job the server cannot read (a value of the wrong type): one error per field. */
function requestIssues(error: ApiError, job: JobSettings): ValidationIssue[] | null {
  if (error.problem.code !== 'request.invalid') return null
  const issues: ValidationIssue[] = []
  for (const field of error.problem.errors ?? []) {
    const path = requestPath(field.loc, job)
    if (path === null) continue
    issues.push({ severity: 'error', code: 'request.invalid', path, message: field.msg })
  }
  return issues.length > 0 ? issues : null
}

/**
 * Keeps the validation store current for the editor's job: `POST /api/jobs/validate`, 250 ms
 * after the last change; a new job at once. Only the answer for the job as it is now is shown.
 * Called once, by the workspace view; the validation stops with the caller's scope.
 */
export function useValidation(): void {
  const editor = useEditorStore()
  const validation = useValidationStore()
  const system = useSystemStore()
  const settings = useSettingsStore()

  function show(issues: ValidationIssue[]): void {
    validation.session = editor.session
    validation.issues = issues
    validation.pending = false
    validation.failed = false
  }

  /** The draft's issues for a job that is the draft's, else none: what is known before an answer. */
  function known(job: JobSettings): ValidationIssue[] {
    const draft = editor.draft
    return draft !== null && draft.job === job ? forJob(draft.issues ?? []) : []
  }

  const request = latestRequest<{ job: JobSettings; issues: ValidationIssue[] }>({
    async send(signal) {
      const job = editor.job as JobSettings
      try {
        const answer = unwrap(await apiQuiet.POST('/api/jobs/validate', { body: { job }, signal }))
        return { job, issues: answer }
      } catch (error) {
        const issues = error instanceof ApiError ? requestIssues(error, job) : null
        if (issues === null) throw error
        return { job, issues }
      }
    },
    done({ job, issues }) {
      show([...forJob(issues), ...forJob(draftIssues(editor.draft, job))])
    },
    failed() {
      validation.pending = false
      validation.failed = true
    },
  })

  function clear(): void {
    request.cancel()
    show([])
  }

  function validate(delay: number): void {
    if (editor.job === null) {
      clear()
      return
    }
    validation.pending = true
    request.schedule(delay)
  }

  function onJob(job: JobSettings | null): void {
    if (job === null) {
      clear()
      return
    }
    if (editor.draft?.job === job) {
      // The draft was validated with the job it holds.
      request.cancel()
      show(known(job))
      return
    }
    if (validation.session !== editor.session) {
      // Another job: its issues are not known yet.
      validation.session = editor.session
      validation.issues = []
      validate(0)
      return
    }
    validate(EDIT_DEBOUNCE)
  }

  // Sync: `pending` is true from the change on, not from the next tick.
  watch(() => editor.job, onJob, { flush: 'sync' })
  // What the issues depend on besides the job: encoder statuses, tools, settings.
  watch(
    [
      () => system.capabilities,
      () => system.info,
      () => settings.settings,
      () => validation.requests,
    ],
    () => validate(EDIT_DEBOUNCE),
  )
  watch(
    () => validation.flushes,
    () => {
      if (validation.pending) request.flush()
      else if (validation.failed) validate(0)
    },
    { flush: 'sync' },
  )
  watch(
    () => system.connection,
    (state) => {
      if (state === 'open' && validation.failed) validate(0)
    },
  )

  // What changed while nothing validated is not known: the open job is validated at once.
  if (editor.job === null) clear()
  else {
    if (validation.session !== editor.session) {
      validation.session = editor.session
      validation.issues = known(editor.job)
    }
    validate(0)
  }

  if (getCurrentScope() !== undefined) {
    onScopeDispose(() => {
      request.cancel()
      validation.pending = false
    })
  }
}
