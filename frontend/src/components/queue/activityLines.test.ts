import { describe, expect, it } from 'vitest'

import type { QueueProcessingEvent, ReframeEvent, Schemas } from '@/api/types'
import { createAppI18n } from '@/i18n'
import type { ActivityEntry, OrderChange } from '@/stores/activity'

import { type ActivityLine, describeEntry } from './activityLines'

const t = createAppI18n().global.t as (key: string, named?: Record<string, unknown>) => string
const jobName = (id: string) => `${id}.mkv`

function line(event: ReframeEvent | QueueProcessingEvent, change?: OrderChange): ActivityLine {
  const entry: ActivityEntry = { id: 1, at: new Date(), event }
  if (change) entry.change = change
  const found = describeEntry(entry, t, jobName)
  if (found === null) throw new Error(`no line for ${event.type}`)
  return found
}

function nothing(event: ReframeEvent | QueueProcessingEvent): boolean {
  return describeEntry({ id: 1, at: new Date(), event }, t, jobName) === null
}

function tool(name: string, status: Schemas['ToolStatus'], version?: string) {
  return { name, status, version } as Schemas['ToolInfo']
}

describe('the activity lines', () => {
  it.each<[string, ReframeEvent | QueueProcessingEvent, Partial<ActivityLine>]>([
    [
      'an added job',
      { type: 'job.state', job_id: 'a', previous: null, state: 'waiting' },
      { kind: 'jobs', text: 'a.mkv was added to the queue' },
    ],
    [
      'a job added as failed, with its error',
      { type: 'job.state', job_id: 'a', previous: null, state: 'failed', error: 'output claimed' },
      { tone: 'error', text: 'a.mkv was added as failed', detail: 'output claimed' },
    ],
    [
      'a start',
      { type: 'job.state', job_id: 'a', previous: 'waiting', state: 'running' },
      { tone: 'busy', text: 'a.mkv started' },
    ],
    [
      'a resume',
      { type: 'job.state', job_id: 'a', previous: 'paused', state: 'running' },
      { text: 'a.mkv resumed' },
    ],
    [
      'a pause',
      { type: 'job.state', job_id: 'a', previous: 'running', state: 'paused' },
      { text: 'a.mkv paused' },
    ],
    [
      'a retry',
      { type: 'job.state', job_id: 'a', previous: 'failed', state: 'waiting' },
      { text: 'a.mkv waits again' },
    ],
    [
      'the end of a run',
      { type: 'job.state', job_id: 'a', previous: 'running', state: 'done' },
      { tone: 'ok', text: 'a.mkv is done' },
    ],
    [
      'a failure, with its error',
      { type: 'job.state', job_id: 'a', previous: 'running', state: 'failed', error: 'x265 broke' },
      { tone: 'error', text: 'a.mkv failed', detail: 'x265 broke' },
    ],
    [
      'a cancel',
      { type: 'job.state', job_id: 'a', previous: 'running', state: 'cancelled' },
      { text: 'a.mkv was cancelled' },
    ],
    [
      'an interruption',
      { type: 'job.state', job_id: 'a', previous: 'running', state: 'interrupted' },
      { tone: 'warn', text: 'a.mkv was interrupted' },
    ],
    [
      'a start of every waiting job',
      { type: 'queue.processing', processing: true, only: null, reason: 'start' },
      { kind: 'queue', text: 'The queue was started: it takes every waiting job' },
    ],
    [
      "another front end's start of some jobs",
      { type: 'queue.processing', processing: true, only: ['a', 'b'], reason: 'start' },
      { text: 'The queue was started for some jobs only (2)' },
    ],
    [
      'a stop',
      { type: 'queue.processing', processing: false, only: null, reason: 'stop' },
      { text: 'The queue was stopped: running jobs go on, no new job starts' },
    ],
    [
      'the idle end of a start',
      { type: 'queue.processing', processing: false, only: null, reason: 'idle' },
      { text: 'The jobs of the last start have all ended' },
    ],
    [
      'a countdown',
      {
        type: 'power.countdown',
        countdown_id: 'p',
        action: 'sleep',
        phase: 'started',
        seconds_left: 60,
      },
      { tone: 'warn', text: 'When done: Sleep in 60 s' },
    ],
    [
      'a cancelled countdown',
      {
        type: 'power.countdown',
        countdown_id: 'p',
        action: 'shutdown',
        phase: 'cancelled',
        seconds_left: 12,
      },
      { text: 'When done: Shut down was cancelled' },
    ],
    [
      'a power action that runs',
      {
        type: 'power.countdown',
        countdown_id: 'p',
        action: 'quit',
        phase: 'executing',
        seconds_left: 0,
      },
      { text: 'When done: Quit Reframe now' },
    ],
    [
      'a warning with its detail',
      {
        type: 'app.warning',
        code: 'settings.corrupt',
        message: 'Settings were reset',
        detail: 'line 3',
      },
      { kind: 'warnings', text: 'Settings were reset', detail: 'line 3' },
    ],
    [
      'a notification, toned by its level',
      { type: 'notification', title: 'Job failed', message: 'a.mkv: broke', level: 'error' },
      { kind: 'notifications', tone: 'error', text: 'Job failed', detail: 'a.mkv: broke' },
    ],
    [
      'a failed task with its error',
      {
        type: 'task.done',
        task: { id: 't', kind: 'probe_sources', state: 'failed', error: 'no such file' },
      },
      { kind: 'tasks', tone: 'error', text: 'Reading sources: failed', detail: 'no such file' },
    ],
    [
      'a task of a kind without a name of its own, in words',
      { type: 'task.done', task: { id: 't', kind: 'thumbnail_sheet', state: 'done' } },
      { kind: 'tasks', tone: 'off', text: 'Thumbnail sheet: done' },
    ],
    [
      'lost events',
      { type: 'resync', reason: 'dropped', dropped: 3 },
      { kind: 'system', text: "Some events were lost: the app read the server's state again" },
    ],
  ])('describes %s', (_, event, expected) => {
    expect(line(event)).toMatchObject(expected)
  })

  it('names every kind of task the server starts', () => {
    const kinds = [
      'probe_sources',
      'encoders_rescan',
      'tools_fetch',
      'bitrate_scan',
      'subtitle_scan',
      'loudness',
      'frames',
      'cropdetect',
      'preview_clip',
    ]
    const texts = kinds.map(
      (kind) =>
        line({ type: 'task.done', task: { id: 't', kind, state: 'cancelled' } } as ReframeEvent)
          .text,
    )
    expect(texts).toEqual([
      'Reading sources: cancelled',
      'Encoder detection: cancelled',
      'FFmpeg download: cancelled',
      'Bitrate measurement: cancelled',
      'Subtitle count: cancelled',
      'Loudness measurement: cancelled',
      'Preview frames: cancelled',
      'Crop detection: cancelled',
      'Preview clip: cancelled',
    ])
  })

  it('names one removed job, and counts several', () => {
    const event: ReframeEvent = { type: 'queue.changed', job_ids: [] }
    expect(line(event, { removed: ['a'], moved: false })).toMatchObject({
      kind: 'jobs',
      text: 'a.mkv was removed from the queue',
    })
    expect(line(event, { removed: ['a', 'b'], moved: false }).text).toBe(
      '2 jobs were removed from the queue',
    )
    expect(line(event, { removed: [], moved: true })).toMatchObject({
      kind: 'queue',
      text: 'The order of the queue changed',
    })
  })

  it('has no line for progress, log lines, ticks or an order that only grew', () => {
    expect(
      nothing({
        type: 'job.progress',
        job_id: 'a',
        progress: { percent: 1, step: 0, step_count: 1 },
      }),
    ).toBe(true)
    expect(nothing({ type: 'job.log', job_id: 'a', lines: ['x'], dropped: 0 })).toBe(true)
    expect(
      nothing({
        type: 'task.progress',
        task: { id: 't', kind: 'probe_sources', state: 'running' },
      }),
    ).toBe(true)
    expect(
      nothing({
        type: 'power.countdown',
        countdown_id: 'p',
        action: 'sleep',
        phase: 'tick',
        seconds_left: 9,
      }),
    ).toBe(true)
    expect(nothing({ type: 'queue.changed', job_ids: ['a'] })).toBe(true)
  })

  it('lists each tool, and is an error when FFmpeg or FFprobe cannot be used', () => {
    const tools = {
      ffmpeg: tool('ffmpeg', 'found', '9.0.2'),
      ffprobe: tool('ffprobe', 'found'),
    }
    const found = line({ type: 'tools.changed', tools } as ReframeEvent)
    expect(found).toMatchObject({ kind: 'system', tone: 'ok' })
    expect(found.detail).toBe('ffmpeg 9.0.2 · ffprobe found')
    const broken = { ...tools, ffprobe: tool('ffprobe', 'too_old') }
    const old = line({ type: 'tools.changed', tools: broken } as ReframeEvent)
    expect(old.tone).toBe('error')
    expect(old.detail).toBe('ffmpeg 9.0.2 · ffprobe too old')
  })

  it('lists the encoders whose status changed with their state', () => {
    const event = {
      type: 'capabilities.changed',
      encoders: [
        { id: 'libx265', state: 'available', hardware: false },
        { id: 'hevc_nvenc', state: 'unavailable', hardware: true },
      ],
    } as ReframeEvent
    expect(line(event)).toMatchObject({
      text: 'Encoder status changed (2)',
      detail: 'libx265: available · hevc_nvenc: unavailable',
    })
  })

  it('words an encoder and its state with one message, which a translation may reorder', () => {
    const i18n = createAppI18n()
    i18n.global.mergeLocaleMessage('en', {
      queue: { activity: { encoderLine: '{state} ({encoder})' } },
    })
    const event = {
      type: 'capabilities.changed',
      encoders: [{ id: 'libx265', state: 'available', hardware: false }],
    } as ReframeEvent
    const reordered = i18n.global.t as (key: string, named?: Record<string, unknown>) => string
    expect(describeEntry({ id: 1, at: new Date(), event }, reordered, jobName)?.detail).toBe(
      'available (libx265)',
    )
  })
})
