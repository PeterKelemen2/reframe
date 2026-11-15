import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'

import type { JobProgress } from '@/api/types'
import { createAppI18n, en } from '@/i18n'

import { jobActions, liveColumns, runState, stepText } from './format'
import { job } from './testing'

const { t, n } = createAppI18n().global

function progress(extra: Partial<JobProgress> = {}): JobProgress {
  return { percent: 40, step: 0, step_count: 1, step_kind: 'encode', ...extra }
}

describe('the step of a running job', () => {
  it('names the pass of a two-pass encode and where it is among the steps', () => {
    expect(stepText(progress({ step_kind: 'pass1', step: 0, step_count: 3 }), t)).toBe(
      'Pass 1 of 2 · step 1 of 3',
    )
  })

  // Before the next test, whose merged message the shared English messages keep.
  it('names the header edit, alone in place or after an encode', () => {
    expect(stepText(progress({ step_kind: 'header_edit' }), t)).toBe('Writing the MKV header')
    expect(stepText(progress({ step_kind: 'header_edit', step: 1, step_count: 3 }), t)).toBe(
      'Writing the MKV header · step 2 of 3',
    )
  })

  it('joins the kind and the step with one message, which a translation may reorder', () => {
    const i18n = createAppI18n()
    i18n.global.mergeLocaleMessage('en', { queue: { step: { withKind: '{step}: {kind}' } } })
    const reordered = i18n.global.t as (key: string, named?: Record<string, unknown>) => string
    expect(stepText(progress({ step_kind: 'analyse', step: 0, step_count: 2 }), reordered)).toBe(
      'step 1 of 2: Analysing',
    )
  })

  it('says nothing for a plain one-step encode, but names a lone step of another kind', () => {
    expect(stepText(progress(), t)).toBeNull()
    expect(stepText(progress({ step_kind: 'finalize' }), t)).toBe('Finishing')
  })

  it('counts the steps when the kind is not known', () => {
    expect(stepText(progress({ step_kind: null, step: 1, step_count: 2 }), t)).toBe('step 2 of 2')
  })
})

describe('the live columns', () => {
  it('shows progress, fps, speed, time left and size of a running job', () => {
    const running = job('a', 'running', {
      progress: progress({
        percent: 27.53,
        fps: 3.84,
        speed: 0.666,
        eta: 83,
        output_size: 3 * 1024 ** 2,
      }),
    })
    expect(liveColumns(running, t, n)).toEqual({
      percent: 27.53,
      percentText: '27.5 %',
      step: null,
      fps: '3.8 fps',
      speed: '0.67×',
      eta: '1:23',
      size: '3.0 MiB',
    })
  })

  it('writes the numbers as the locale does', () => {
    const german = createI18n({
      legacy: false,
      locale: 'de',
      fallbackLocale: 'en',
      messages: { en },
      missingWarn: false,
      fallbackWarn: false,
    }).global
    const running = job('a', 'running', {
      progress: progress({ percent: 27.53, fps: 3.84, speed: 0.666 }),
    })
    const columns = liveColumns(running, german.t, german.n)
    expect([columns.percentText, columns.fps, columns.speed]).toEqual([
      '27,5 %',
      '3,8 fps',
      '0,67×',
    ])
  })

  it('leaves out the time left of a paused job', () => {
    const paused = job('a', 'paused', { progress: progress({ eta: 83 }) })
    expect(liveColumns(paused, t, n).eta).toBeNull()
    expect(liveColumns(paused, t, n).percent).toBe(40)
  })

  it('shows a done job full and a waiting or ended one empty', () => {
    expect(liveColumns(job('a', 'done'), t, n).percent).toBe(100)
    expect(liveColumns(job('a', 'done'), t, n).percentText).toBe('100.0 %')
    // A progress left on a job that is no longer running is not shown.
    expect(liveColumns(job('a', 'failed', { progress: progress() }), t, n).percent).toBeNull()
    expect(liveColumns(job('a', 'waiting'), t, n).percentText).toBeNull()
  })
})

describe('the actions of a job', () => {
  it.each([
    ['waiting', ['cancel', 'log', 'edit', 'duplicate', 'remove']],
    ['running', ['pause', 'cancel', 'log', 'edit', 'duplicate']],
    ['paused', ['resume', 'cancel', 'log', 'edit', 'duplicate']],
    ['done', ['log', 'edit', 'duplicate', 'remove']],
    ['failed', ['retry', 'log', 'edit', 'duplicate', 'remove']],
    ['cancelled', ['retry', 'log', 'edit', 'duplicate', 'remove']],
    ['interrupted', ['retry', 'log', 'edit', 'duplicate', 'remove']],
  ] as const)('a %s job offers %j', (state, actions) => {
    expect(jobActions(job('a', state), false)).toEqual(actions)
  })

  it('offers reveal in folder only on the desktop, for a done job', () => {
    expect(jobActions(job('a', 'done'), true)).toContain('reveal')
    expect(jobActions(job('a', 'failed'), true)).not.toContain('reveal')
  })
})

describe('the run state', () => {
  const jobs = [job('a', 'running'), job('b', 'waiting'), job('c', 'waiting')]

  it('counts the waiting jobs a Start would take while stopped', () => {
    expect(runState(false, null, jobs)).toEqual({ mode: 'stopped', onlyCount: 0, held: 2 })
  })

  it('takes every waiting job without `only`', () => {
    expect(runState(true, null, jobs)).toEqual({ mode: 'all', onlyCount: 0, held: 0 })
  })

  it('counts only the named jobs still in the queue, and the waiting jobs left out', () => {
    // `gone` left the queue; the server keeps its id until the run goes idle.
    expect(runState(true, ['a', 'gone'], jobs)).toEqual({ mode: 'only', onlyCount: 1, held: 2 })
    expect(runState(true, ['b'], jobs)).toEqual({ mode: 'only', onlyCount: 1, held: 1 })
  })
})
