import { applyPatch, createPatch, type Operation } from 'rfc6902'

import type { JsonPatchOp } from '@/api/types'

/** A patch that does not apply to the document; the document is unchanged. */
export class PatchError extends Error {
  constructor(
    readonly op: JsonPatchOp,
    readonly reason: string,
  ) {
    super(`${op.op} ${op.path}: ${reason}`)
    this.name = 'PatchError'
  }
}

/** A deep copy with JSON's semantics: what the server will see. */
export function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

/** Freezes `value` and everything in it, so a change can only come through a patch. */
export function deepFreeze<T>(value: T): T {
  if (typeof value === 'object' && value !== null && !Object.isFrozen(value)) {
    Object.freeze(value)
    for (const child of Object.values(value)) deepFreeze(child)
  }
  return value
}

/**
 * A frozen copy of `document` with `ops` applied: all of them, or none (`PatchError`). A
 * `replace` or `add` of the whole document (`''`) is applied too.
 */
export function applyOps<T>(document: T, ops: readonly JsonPatchOp[]): T {
  let copy: unknown = cloneJson(document)
  for (const op of ops) {
    if (op.path === '' && (op.op === 'replace' || op.op === 'add')) {
      copy = cloneJson(op.value)
      continue
    }
    const [result] = applyPatch(copy, [op as Operation])
    if (result) throw new PatchError(op, result.message)
  }
  return deepFreeze(copy as T)
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Whether member-wise `remove` and `add` turn `before`'s keys into `after`'s in their order:
 * an added key always lands at the end.
 */
function keepsOrder(before: Record<string, unknown>, after: Record<string, unknown>): boolean {
  const expected = [
    ...Object.keys(before).filter((key) => Object.hasOwn(after, key)),
    ...Object.keys(after).filter((key) => !Object.hasOwn(before, key)),
  ]
  const actual = Object.keys(after)
  return expected.every((key, index) => key === actual[index])
}

/**
 * The patch from `before` to `after`. Applied to `before`, it gives `after` with its key order
 * too (filters and advanced options are shown in that order): an object whose keys a member-wise
 * patch would reorder is replaced whole.
 */
export function diffJson(before: unknown, after: unknown): JsonPatchOp[] {
  const ops = createPatch(before, after, (input: unknown, output: unknown, pointer) => {
    if (isObject(input) && isObject(output) && !keepsOrder(input, output)) {
      return [{ op: 'replace', path: pointer.toString(), value: output }]
    }
    return undefined
  })
  return ops as JsonPatchOp[]
}

/** Equal as JSON documents (key order aside). */
export function sameJson(a: unknown, b: unknown): boolean {
  return a === b || createPatch(a, b).length === 0
}
