import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'

import { deferred, problem, type Recorded } from '@/api/testing/fakes'
import type { JobSettings, Schemas, ValidationIssue } from '@/api/types'
import { EDIT_DEBOUNCE } from '@/stores/editor'

import { openJob, setUpVideo, snapshot } from './testing'
import { useCommandPlan } from './useCommandPlan'

type EncodePlan = Schemas['EncodePlan']

function planFor(job: JobSettings): EncodePlan {
  const value = job.video?.rate_control?.mode === 'quality' ? job.video.rate_control.value : 0
  return {
    job_type: 'encode',
    steps: [],
    output_tmp: '/out/a.part.mkv',
    output_final: '/out/a.mkv',
    expected_duration: 4,
    display: `ffmpeg -crf ${value}`,
  }
}

function issue(severity: ValidationIssue['severity']): ValidationIssue {
  return { severity, code: `test.${severity}`, path: 'video.encoder', message: severity }
}

function sentValue(request: Recorded): unknown {
  return (request.body as { job: JobSettings }).job.video?.rate_control
}

describe('useCommandPlan', () => {
  let setup: ReturnType<typeof setUpVideo>
  let scope = effectScope()

  beforeEach(async () => {
    scope = effectScope()
    setup = setUpVideo()
    setup.server.on('POST /api/jobs/plan', (request) =>
      planFor((request.body as { job: JobSettings }).job),
    )
    await openJob()
    vi.useFakeTimers()
  })

  afterEach(() => {
    scope.stop()
    vi.useRealTimers()
  })

  function start(active = true) {
    const open = ref(active)
    const plan = scope.run(() => useCommandPlan(open))!
    return { open, ...plan }
  }

  const plans = () => setup.server.count('POST /api/jobs/plan')

  it('asks nothing while closed, and at once when opened', async () => {
    const { open, plan } = start(false)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE * 2)
    expect(plans()).toBe(0)
    open.value = true
    await vi.advanceTimersByTimeAsync(0)
    expect(plans()).toBe(1)
    expect(plan.value?.display).toBe('ffmpeg -crf 22')
  })

  it('asks once, after the last of several edits, for the newest job', async () => {
    const { plan, pending } = start()
    await vi.advanceTimersByTimeAsync(0)
    setup.editor.set('/video/rate_control/value', 23)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 50)
    setup.editor.set('/video/rate_control/value', 24)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 50)
    setup.editor.set('/video/rate_control/value', 25)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 50)
    expect(plans()).toBe(1)
    expect(pending.value).toBe(true)
    await vi.advanceTimersByTimeAsync(50)
    expect(plans()).toBe(2)
    expect(sentValue(setup.server.requests.at(-1)!)).toEqual({ mode: 'quality', value: 25 })
    expect(plan.value?.display).toBe('ffmpeg -crf 25')
    expect(pending.value).toBe(false)
  })

  it('never shows an older answer over a newer one', async () => {
    const slow = deferred<EncodePlan>()
    setup.server.on('POST /api/jobs/plan', (request) => {
      const job = (request.body as { job: JobSettings }).job
      return job.video?.rate_control?.mode === 'quality' && job.video.rate_control.value === 22
        ? slow.promise
        : planFor(job)
    })
    const { plan } = start()
    await vi.advanceTimersByTimeAsync(0)
    setup.editor.set('/video/rate_control/value', 30)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(plan.value?.display).toBe('ffmpeg -crf 30')
    slow.resolve({ ...planFor(setup.editor.job!), display: 'ffmpeg -crf 22' })
    await vi.advanceTimersByTimeAsync(0)
    expect(plan.value?.display).toBe('ffmpeg -crf 30')
  })

  it("shows the job's errors when the server makes no command", async () => {
    const body = {
      type: 'about:blank',
      title: 'The job has errors',
      status: 422,
      code: 'jobs.invalid',
      issues: [issue('error'), issue('warning')],
    }
    setup.server.on(
      'POST /api/jobs/plan',
      () =>
        new Response(JSON.stringify(body), {
          status: 422,
          headers: { 'Content-Type': 'application/problem+json' },
        }),
    )
    const { plan, problem: shown } = start()
    await vi.advanceTimersByTimeAsync(0)
    expect(plan.value).toBeNull()
    expect(shown.value).toEqual({ kind: 'invalid', issues: [issue('error')] })
  })

  it('shows why another failure made no command', async () => {
    setup.server.on('POST /api/jobs/plan', () =>
      problem(500, 'internal', 'Server error', 'ffmpeg not found'),
    )
    const { problem: shown } = start()
    await vi.advanceTimersByTimeAsync(0)
    expect(shown.value).toEqual({ kind: 'failed', message: 'ffmpeg not found' })
  })

  it('asks again when the encoder statuses change', async () => {
    start()
    await vi.advanceTimersByTimeAsync(0)
    setup.system.capabilities = snapshot({ detecting: true })
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(plans()).toBe(2)
  })

  it('forgets the command when the editor closes', async () => {
    const { plan } = start()
    await vi.advanceTimersByTimeAsync(0)
    setup.editor.close()
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(plan.value).toBeNull()
    expect(plans()).toBe(1)
  })
})
