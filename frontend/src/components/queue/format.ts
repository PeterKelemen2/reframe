import type { JobProgress, JobState, QueueJob } from '@/api/types'
import type { StatusTone } from '@/components/base/types'
import { fileName, formatDuration } from '@/components/shell/format'
import { formatBytes, type Translate } from '@/components/summary/format'

export const STATE_TONE: Record<JobState, StatusTone> = {
  waiting: 'off',
  running: 'busy',
  paused: 'warn',
  done: 'ok',
  failed: 'error',
  cancelled: 'off',
  interrupted: 'warn',
}

export function stateLabel(state: JobState, t: Translate): string {
  switch (state) {
    case 'waiting':
      return t('queue.state.waiting')
    case 'running':
      return t('queue.state.running')
    case 'paused':
      return t('queue.state.paused')
    case 'done':
      return t('queue.state.done')
    case 'failed':
      return t('queue.state.failed')
    case 'cancelled':
      return t('queue.state.cancelled')
    case 'interrupted':
      return t('queue.state.interrupted')
  }
}

/** The running step: `Pass 1 of 2`, `Encoding · step 2 of 3`; `null` for a one-step encode. */
export function stepText(progress: JobProgress, t: Translate): string | null {
  const kind = (() => {
    switch (progress.step_kind) {
      case 'analyse':
        return t('queue.step.analyse')
      case 'pass1':
        return t('queue.step.pass1')
      case 'pass2':
        return t('queue.step.pass2')
      case 'encode':
        return t('queue.step.encode')
      case 'mkvpropedit':
        return t('queue.step.mkvpropedit')
      case 'finalize':
        return t('queue.step.finalize')
      case null:
      case undefined:
        return null
    }
  })()
  if (progress.step_count <= 1) {
    return progress.step_kind === 'encode' ? null : kind
  }
  const step = t('queue.step.of', { n: progress.step + 1, count: progress.step_count })
  return kind === null ? step : `${kind} · ${step}`
}

/** The live columns of a running or paused job; `null` where the job has no value. */
export interface LiveColumns {
  percent: number | null
  step: string | null
  fps: string | null
  speed: string | null
  eta: string | null
  size: string | null
}

const NONE: LiveColumns = {
  percent: null,
  step: null,
  fps: null,
  speed: null,
  eta: null,
  size: null,
}

function known(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value)
}

export function liveColumns(job: QueueJob, t: Translate): LiveColumns {
  if (job.state === 'done') return { ...NONE, percent: 100 }
  const progress = job.progress
  if ((job.state !== 'running' && job.state !== 'paused') || !progress) return NONE
  return {
    percent: Math.max(0, Math.min(100, progress.percent)),
    step: stepText(progress, t),
    fps: known(progress.fps) ? t('queue.units.fps', { value: progress.fps.toFixed(1) }) : null,
    speed: known(progress.speed)
      ? t('queue.units.speed', { value: progress.speed.toFixed(2) })
      : null,
    eta: job.state === 'running' ? formatDuration(progress.eta) : null,
    size: known(progress.output_size) ? formatBytes(progress.output_size, t) : null,
  }
}

export function sourceName(job: QueueJob): string {
  return fileName(job.settings.source.path)
}

/** The output's file name: the final one once the run chose it, else the planned one. */
export function outputPath(job: QueueJob): string | null {
  return job.output_path || job.settings.output?.path || null
}

export type JobAction =
  | 'pause'
  | 'resume'
  | 'cancel'
  | 'retry'
  | 'duplicate'
  | 'edit'
  | 'remove'
  | 'log'
  | 'reveal'

/** The actions that fit the job's state, in the row's order. */
export function jobActions(job: QueueJob, canReveal: boolean): JobAction[] {
  const actions: JobAction[] = []
  switch (job.state) {
    case 'running':
      actions.push('pause', 'cancel')
      break
    case 'paused':
      actions.push('resume', 'cancel')
      break
    case 'waiting':
      actions.push('cancel')
      break
    case 'failed':
    case 'cancelled':
    case 'interrupted':
      actions.push('retry')
      break
    case 'done':
      break
  }
  actions.push('log', 'edit', 'duplicate')
  if (job.state !== 'running' && job.state !== 'paused') actions.push('remove')
  if (canReveal && job.state === 'done' && outputPath(job) !== null) actions.push('reveal')
  return actions
}

/**
 * What the runner takes: every waiting job, only some (another front end's start with job
 * ids), or none (stopped). `onlyCount` counts the named jobs still in the queue: `only` keeps
 * the ids of jobs that have left it until the run goes idle.
 */
export interface RunState {
  mode: 'all' | 'only' | 'stopped'
  onlyCount: number
  /** Waiting jobs the runner does not take now: a Start would run them. */
  held: number
}

export function runState(
  processing: boolean,
  only: readonly string[] | null,
  jobs: readonly QueueJob[],
): RunState {
  const waiting = jobs.filter((job) => job.state === 'waiting')
  if (!processing) return { mode: 'stopped', onlyCount: 0, held: waiting.length }
  if (only === null) return { mode: 'all', onlyCount: 0, held: 0 }
  const named = new Set(only)
  return {
    mode: 'only',
    onlyCount: jobs.filter((job) => named.has(job.id)).length,
    held: waiting.filter((job) => !named.has(job.id)).length,
  }
}
