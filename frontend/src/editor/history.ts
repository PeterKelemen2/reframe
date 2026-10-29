import type { JsonPatchOp } from '@/api/types'

import { diffJson } from './patch'

/** One undo step: each patch turns the document on one side of the step into the other. */
export interface Step {
  redo: JsonPatchOp[]
  undo: JsonPatchOp[]
}

/** Patches in a row with one coalescing key: they make one step. */
interface Run {
  key: string
  /** The document before the run's first patch. */
  before: unknown
  /** The run's step, the last of `done`; `null` while the run changed nothing. */
  step: Step | null
}

export interface History {
  readonly done: readonly Step[]
  readonly undone: readonly Step[]
  readonly run: Run | null
}

/** Steps kept; the oldest is dropped beyond. */
export const HISTORY_LIMIT = 200

export const EMPTY_HISTORY: History = { done: [], undone: [], run: null }

function stepOf(before: unknown, after: unknown): Step | null {
  const redo = diffJson(before, after)
  return redo.length === 0 ? null : { redo, undo: diffJson(after, before) }
}

function bounded(steps: readonly Step[], limit: number): readonly Step[] {
  return steps.length > limit ? steps.slice(steps.length - limit) : steps
}

/**
 * The history after a change from `before` to `after`. With the open run's `key` the change
 * joins that run's step; any other change ends the run. A change that changes nothing adds no
 * step and keeps the steps to redo.
 */
export function record(
  history: History,
  before: unknown,
  after: unknown,
  key: string | null = null,
  limit = HISTORY_LIMIT,
): History {
  const run = history.run
  if (key !== null && run !== null && run.key === key) {
    const done = run.step === null ? history.done : history.done.slice(0, -1)
    const step = stepOf(run.before, after)
    return {
      done: step === null ? done : bounded([...done, step], limit),
      undone: step === null ? history.undone : [],
      run: { key, before: run.before, step },
    }
  }
  const step = stepOf(before, after)
  return {
    done: step === null ? history.done : bounded([...history.done, step], limit),
    undone: step === null ? history.undone : [],
    run: key === null ? null : { key, before, step },
  }
}

/** The step to undo and the history once it is undone; `null` when there is none. */
export function undoStep(history: History): { step: Step; history: History } | null {
  const step = history.done.at(-1)
  if (step === undefined) return null
  return {
    step,
    history: { done: history.done.slice(0, -1), undone: [...history.undone, step], run: null },
  }
}

/** The step to redo and the history once it is redone; `null` when there is none. */
export function redoStep(history: History): { step: Step; history: History } | null {
  const step = history.undone.at(-1)
  if (step === undefined) return null
  return {
    step,
    history: { done: [...history.done, step], undone: history.undone.slice(0, -1), run: null },
  }
}

/** The history with its open run ended: the next patch starts a step of its own. */
export function endRun(history: History): History {
  return history.run === null ? history : { ...history, run: null }
}
