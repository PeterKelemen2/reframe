import type {
  BatchResolution,
  BatchRun,
  JobSettings,
  JsonPatchOp,
  TemplateSection,
} from '@/api/types'

import { sameJson } from './patch'
import { tokensOf, valueAt } from './pointer'
import { generatedNames } from './template'

/**
 * The job fields that a template cannot hold, by pointer, with the `editor.group.fields` key
 * that names them.
 */
const PER_FILE: readonly (readonly [string, string])[] = [
  ['/range', 'range'],
  ['/source', 'source'],
  ['/output/path', 'outputPath'],
  ['/output/edit_in_place', 'editInPlace'],
  ['/output/naming/mode', 'namingMode'],
  ['/output/naming/manual_name', 'manualName'],
  ['/output/naming/field_overrides', 'nameFields'],
  ['/video/metadata', 'videoMetadata'],
  ['/chapters/names', 'chapterNames'],
  ['/preset_id', 'preset'],
  ['/preset_name', 'preset'],
]

const SECTIONS: Readonly<Record<string, TemplateSection>> = {
  dimensions: 'dimensions',
  filters: 'filters',
  video: 'video',
  audio: 'audio',
  subtitles: 'subtitles',
  chapters: 'chapters',
  tags: 'tags',
}

const ALL_SECTIONS = Object.values(SECTIONS).concat('naming')

/** `pointer` is `parent` or below it. */
export function within(pointer: string, parent: string): boolean {
  return pointer === parent || pointer.startsWith(`${parent}/`)
}

/** One pointer is the other or below it: an operation at one sets the value at the other. */
export function related(a: string, b: string): boolean {
  return within(a, b) || within(b, a)
}

function sameValue(a: unknown, b: unknown): boolean {
  return a === undefined || b === undefined ? a === b : sameJson(a, b)
}

function external(track: { source?: unknown }): boolean {
  return typeof track.source === 'object' && track.source !== null
}

function externals(job: JobSettings): unknown[] {
  return (job.subtitles ?? []).filter(external)
}

/**
 * The `editor.group.fields` key of the first field that only a file can hold and that differs
 * from `before` in `after`; `null` when the template can hold the change. Chapter names that
 * the template's name policy gives (none, or `Chapter 1…n`) are not per file.
 */
export function perFileChange(before: JobSettings, after: JobSettings): string | null {
  for (const [pointer, field] of PER_FILE) {
    const now = valueAt(after, pointer)
    if (sameValue(valueAt(before, pointer), now)) continue
    if (
      pointer === '/chapters/names' &&
      (now === null || (Array.isArray(now) && generatedNames(now)))
    ) {
      continue
    }
    return field
  }
  return sameJson(externals(before), externals(after)) ? null : 'externalSubtitle'
}

/** A value at `pointer` of `job` is set per file: the template cannot hold it. */
export function perFilePointer(pointer: string, job: JobSettings | null): boolean {
  if (PER_FILE.some(([perFile]) => within(pointer, perFile))) return true
  const [first, index] = tokensOf(pointer)
  if (first !== 'subtitles' || index === undefined) return false
  const track = job?.subtitles?.[Number(index)]
  return track !== undefined && external(track)
}

/**
 * The template sections that `changes` (a patch of a job) touch, and whether they touch the
 * output options, which no section carries.
 */
export function sectionsOf(changes: readonly JsonPatchOp[]): {
  sections: TemplateSection[]
  output: boolean
} {
  const sections = new Set<TemplateSection>()
  let output = false
  for (const op of changes) {
    const [first, second] = tokensOf(op.path)
    if (first === undefined) {
      for (const section of ALL_SECTIONS) sections.add(section)
      output = true
      continue
    }
    const section = SECTIONS[first]
    if (section !== undefined) sections.add(section)
    if (first !== 'output') continue
    if (second === undefined || second === 'naming') sections.add('naming')
    if (second === undefined || !['naming', 'path', 'edit_in_place'].includes(second)) output = true
  }
  return { sections: [...sections], output }
}

/** An operation at `pointer` changes a track list (`element`: a whole track replaced does not). */
function inTrackList(pointer: string, element: boolean): boolean {
  const tokens = tokensOf(pointer)
  if (tokens.length === 0) return true
  if (tokens[0] !== 'audio' && tokens[0] !== 'subtitles') return false
  return tokens.length === 1 || (tokens.length === 2 && !element)
}

/** `op` adds, removes or moves an output track, or replaces a whole track list. */
export function changesTrackList(op: JsonPatchOp): boolean {
  if (op.op === 'test') return false
  if (inTrackList(op.path, op.op === 'replace')) return true
  return op.op === 'move' && inTrackList(op.from, false)
}

/** The operation on the per-file document: `/job` in front of its paths. */
export function inJob(op: JsonPatchOp): JsonPatchOp {
  return 'from' in op
    ? { ...op, path: `/job${op.path}`, from: `/job${op.from}` }
    : { ...op, path: `/job${op.path}` }
}

/**
 * What an operation's `test` guard checks: the whole output track (`/job/audio/1`) for an
 * operation inside one, the rule's selector (`/audio_rules/1/selector`) for a hand pick.
 */
function guardPath(pointer: string): string | null {
  const [first, second, third] = tokensOf(pointer)
  if (first === 'job' && (second === 'audio' || second === 'subtitles')) {
    return third !== undefined && /^\d+$/.test(third) ? `/job/${second}/${third}` : null
  }
  if ((first === 'audio_rules' || first === 'subtitle_rules') && third === 'selector') {
    return second !== undefined && /^\d+$/.test(second) ? `/${first}/${second}/selector` : null
  }
  return null
}

/**
 * The override in its order: the operations without a guard, then per track or rule its `test`
 * guard and its operations. A failed `test` skips the rest of its part (template or job), so
 * an unguarded operation must come before every guard. Guards left without an operation are
 * dropped.
 */
export function ordered(ops: readonly JsonPatchOp[]): JsonPatchOp[] {
  const outside: JsonPatchOp[] = []
  const tracks = new Map<string, { guard: JsonPatchOp | null; ops: JsonPatchOp[] }>()
  for (const op of ops) {
    const guard = guardPath(op.path)
    if (guard === null) {
      outside.push(op)
      continue
    }
    const track = tracks.get(guard) ?? { guard: null, ops: [] }
    tracks.set(guard, track)
    if (op.op === 'test') track.guard ??= op
    else track.ops.push(op)
  }
  const result = outside
  for (const track of tracks.values()) {
    if (track.ops.length === 0) continue
    if (track.guard !== null) result.push(track.guard)
    result.push(...track.ops)
  }
  return result
}

/**
 * `override` with `ops` (paths of the per-file document) merged in: an earlier operation on
 * the same path or below it is replaced. An operation inside an output track comes after a
 * `test` of the whole track as `job` (the file's job now) has it before the track's first
 * operation, so that a template change of that track or of its place makes the override stale
 * instead of applying it to another track. A later operation keeps that first guard.
 */
export function mergeOverride(
  override: readonly JsonPatchOp[],
  ops: readonly JsonPatchOp[],
  job: JobSettings,
): JsonPatchOp[] {
  let merged = [...override]
  // A test of the edit itself was checked on the shown job: in the override it would only skip.
  for (const op of ops.filter((one) => one.op !== 'test')) {
    merged = merged.filter((earlier) => earlier.op === 'test' || !within(earlier.path, op.path))
    const guard = guardPath(op.path)
    if (
      guard !== null &&
      !merged.some((earlier) => earlier.op === 'test' && earlier.path === guard)
    ) {
      merged.push({
        op: 'test',
        path: guard,
        value: valueAt({ job }, guard) ?? null,
      } as JsonPatchOp)
    }
    merged.push(op)
  }
  return ordered(merged)
}

/** `override` without the operations `drop` names, and the guards they leave alone. */
export function withoutOps(
  override: readonly JsonPatchOp[],
  drop: (op: JsonPatchOp) => boolean,
): JsonPatchOp[] {
  return ordered(override.filter((op) => op.op === 'test' || !drop(op)))
}

/** The resolutions of a batch run as one matrix: the first one's columns, every row and issue. */
export function mergedResolutions(run: BatchRun): BatchResolution {
  const [first] = run.resolutions
  return {
    group: first?.group ?? null,
    columns: first?.columns ?? [],
    rows: run.resolutions.flatMap((resolution) => resolution.rows ?? []),
    issues: run.resolutions.flatMap((resolution) => resolution.issues ?? []),
  }
}
