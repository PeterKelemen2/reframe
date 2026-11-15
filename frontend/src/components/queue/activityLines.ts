import type { EventOf, JobState, Schemas } from '@/api/types'
import type { StatusTone } from '@/components/base/types'
import type { Translate } from '@/components/summary/format'
import type { ActivityEntry } from '@/stores/activity'

/** The groups of the activity view's filter. */
export type ActivityKind = 'jobs' | 'queue' | 'system' | 'warnings' | 'notifications' | 'tasks'

export const ACTIVITY_KINDS: readonly ActivityKind[] = [
  'jobs',
  'queue',
  'system',
  'warnings',
  'notifications',
  'tasks',
]

export interface ActivityLine {
  kind: ActivityKind
  tone: StatusTone
  text: string
  detail?: string
}

/** A job's name for a line: its source file name, or a short id when it was never seen. */
export type JobNamer = (jobId: string) => string

type PowerAction = EventOf<'power.countdown'>['action']
type EncoderState = Schemas['EncoderState']
type ToolInfo = Schemas['ToolInfo']

export function powerActionName(action: PowerAction, t: Translate): string {
  switch (action) {
    case 'sleep':
      return t('queue.whenDone.sleep')
    case 'shutdown':
      return t('queue.whenDone.shutdown')
    case 'quit':
      return t('queue.whenDone.quit')
  }
}

function encoderState(state: EncoderState, t: Translate): string {
  switch (state) {
    case 'available':
      return t('queue.activity.encoder.available')
    case 'unavailable':
      return t('queue.activity.encoder.unavailable')
    case 'checking':
      return t('queue.activity.encoder.checking')
    case 'error':
      return t('queue.activity.encoder.error')
    case 'unknown':
      return t('queue.activity.encoder.unknown')
  }
}

function toolText(tool: ToolInfo, t: Translate): string {
  switch (tool.status) {
    case 'found':
      return tool.version
        ? t('queue.activity.tool.found', { name: tool.name, version: tool.version })
        : t('queue.activity.tool.foundNoVersion', { name: tool.name })
    case 'missing':
      return t('queue.activity.tool.missing', { name: tool.name })
    case 'too_old':
      return t('queue.activity.tool.tooOld', { name: tool.name })
    case 'broken':
      return t('queue.activity.tool.broken', { name: tool.name })
  }
}

function line(tone: StatusTone, text: string, detail?: string): ActivityLine {
  return detail === undefined ? { kind: 'jobs', tone, text } : { kind: 'jobs', tone, text, detail }
}

function jobLine(event: EventOf<'job.state'>, name: string, t: Translate): ActivityLine {
  const error = event.error ?? undefined
  if (event.previous == null) {
    return event.state === 'failed'
      ? line('error', t('queue.activity.job.addedFailed', { job: name }), error)
      : line('off', t('queue.activity.job.added', { job: name }))
  }
  const state: JobState = event.state
  switch (state) {
    case 'waiting':
      return line('off', t('queue.activity.job.waiting', { job: name }))
    case 'running':
      return event.previous === 'paused'
        ? line('busy', t('queue.activity.job.resumed', { job: name }))
        : line('busy', t('queue.activity.job.started', { job: name }))
    case 'paused':
      return line('warn', t('queue.activity.job.paused', { job: name }))
    case 'done':
      return line('ok', t('queue.activity.job.done', { job: name }))
    case 'failed':
      return line('error', t('queue.activity.job.failed', { job: name }), error)
    case 'cancelled':
      return line('off', t('queue.activity.job.cancelled', { job: name }))
    case 'interrupted':
      return line('warn', t('queue.activity.job.interrupted', { job: name }), error)
  }
}

function processingLine(event: EventOf<'queue.processing'>, t: Translate): ActivityLine {
  switch (event.reason) {
    case 'start':
      return {
        kind: 'queue',
        tone: 'busy',
        text:
          event.only === null
            ? t('queue.activity.processing.startAll')
            : t('queue.activity.processing.startOnly', { n: event.only.length }),
      }
    case 'stop':
      return { kind: 'queue', tone: 'off', text: t('queue.activity.processing.stop') }
    case 'idle':
      return { kind: 'queue', tone: 'off', text: t('queue.activity.processing.idle') }
  }
}

function countdownLine(event: EventOf<'power.countdown'>, t: Translate): ActivityLine {
  const action = powerActionName(event.action, t)
  switch (event.phase) {
    case 'started':
    case 'tick':
      return {
        kind: 'queue',
        tone: 'warn',
        text: t('queue.activity.power.started', { action, seconds: event.seconds_left }),
      }
    case 'cancelled':
      return { kind: 'queue', tone: 'off', text: t('queue.activity.power.cancelled', { action }) }
    case 'executing':
      return { kind: 'queue', tone: 'warn', text: t('queue.activity.power.executing', { action }) }
  }
}

/** A task's kind in words; a kind without a message is shown with spaces and a capital. */
export function taskName(kind: string, t: Translate): string {
  switch (kind) {
    case 'probe_sources':
      return t('queue.activity.taskKind.probe_sources')
    case 'probe_folder':
      return t('queue.activity.taskKind.probe_folder')
    case 'encoders_rescan':
      return t('queue.activity.taskKind.encoders_rescan')
    case 'tools_fetch':
      return t('queue.activity.taskKind.tools_fetch')
    case 'bitrate_scan':
      return t('queue.activity.taskKind.bitrate_scan')
    case 'subtitle_scan':
      return t('queue.activity.taskKind.subtitle_scan')
    case 'loudness':
      return t('queue.activity.taskKind.loudness')
    case 'frames':
      return t('queue.activity.taskKind.frames')
    case 'cropdetect':
      return t('queue.activity.taskKind.cropdetect')
    case 'preview_clip':
      return t('queue.activity.taskKind.preview_clip')
  }
  const spaced = kind.replaceAll('_', ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

const TONE_OF_LEVEL: Record<EventOf<'notification'>['level'], StatusTone> = {
  info: 'off',
  success: 'ok',
  warning: 'warn',
  error: 'error',
}

/**
 * One readable line for an entry of the activity log; `null` for the entries that say nothing
 * on their own (progress, log lines, countdown ticks, an order that only grew).
 */
export function describeEntry(
  entry: ActivityEntry,
  t: Translate,
  name: JobNamer,
): ActivityLine | null {
  const event = entry.event
  switch (event.type) {
    case 'job.state':
      return jobLine(event, name(event.job_id), t)
    case 'queue.changed': {
      if (entry.change === undefined) return null
      const removed = entry.change.removed
      if (removed.length === 0) {
        return { kind: 'queue', tone: 'off', text: t('queue.activity.order') }
      }
      const [only] = removed
      return {
        kind: 'jobs',
        tone: 'off',
        text:
          removed.length === 1 && only !== undefined
            ? t('queue.activity.job.removed', { job: name(only) })
            : t('queue.activity.job.removedMany', { n: removed.length }),
      }
    }
    case 'queue.processing':
      return processingLine(event, t)
    case 'power.countdown':
      return event.phase === 'tick' ? null : countdownLine(event, t)
    case 'tools.changed': {
      const tools = event.tools
      const usable = tools.ffmpeg.status === 'found' && tools.ffprobe.status === 'found'
      return {
        kind: 'system',
        tone: usable ? 'ok' : 'error',
        text: t('queue.activity.tools'),
        detail: [tools.ffmpeg, tools.ffprobe].map((tool) => toolText(tool, t)).join(' · '),
      }
    }
    case 'capabilities.changed':
      return {
        kind: 'system',
        tone: event.encoders.some((encoder) => encoder.state === 'error') ? 'warn' : 'off',
        text: t('queue.activity.encoders', { n: event.encoders.length }),
        detail: event.encoders
          .map((encoder) =>
            t('queue.activity.encoderLine', {
              encoder: encoder.id,
              state: encoderState(encoder.state, t),
            }),
          )
          .join(' · '),
      }
    case 'app.warning':
      return event.detail
        ? { kind: 'warnings', tone: 'warn', text: event.message, detail: event.detail }
        : { kind: 'warnings', tone: 'warn', text: event.message }
    case 'notification':
      return event.message
        ? {
            kind: 'notifications',
            tone: TONE_OF_LEVEL[event.level],
            text: event.title,
            detail: event.message,
          }
        : { kind: 'notifications', tone: TONE_OF_LEVEL[event.level], text: event.title }
    case 'task.done': {
      const task = event.task
      const taskWords = taskName(task.kind, t)
      const text = (() => {
        switch (task.state) {
          case 'done':
            return t('queue.activity.task.done', { task: taskWords })
          case 'failed':
            return t('queue.activity.task.failed', { task: taskWords })
          case 'cancelled':
            return t('queue.activity.task.cancelled', { task: taskWords })
          case 'queued':
          case 'running':
            return t('queue.activity.task.running', { task: taskWords })
        }
      })()
      const tone: StatusTone = task.state === 'failed' ? 'error' : 'off'
      return task.error
        ? { kind: 'tasks', tone, text, detail: task.error }
        : { kind: 'tasks', tone, text }
    }
    case 'resync':
      return { kind: 'system', tone: 'warn', text: t('queue.activity.resync') }
    case 'job.progress':
    case 'job.log':
    case 'task.progress':
      return null
  }
}
