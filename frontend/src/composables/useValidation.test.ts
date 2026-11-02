import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, problem, type Recorded } from '@/api/testing/fakes'
import type { CapabilitySnapshot, JobSettings, ValidationIssue } from '@/api/types'
import { issue, sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'
import { useSettingsStore } from '@/stores/settings'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'
import { useValidationStore } from '@/stores/validation'

import { useValidation } from './useValidation'

const CROP = issue('dimensions.crop_not_detected', 'dimensions.crop', 'info')

function sentJob(request: Recorded | undefined): JobSettings {
  return (request!.body as { job: JobSettings }).job
}

async function opened() {
  const editor = useEditorStore()
  await editor.open('movie')
  await vi.advanceTimersByTimeAsync(0)
  return editor
}

/** Runs `each` for one item after the other: edits that must come in turn. */
async function inTurn<T>(items: readonly T[], each: (item: T) => Promise<void>): Promise<void> {
  const [first, ...rest] = items
  if (first === undefined) return
  await each(first)
  await inTurn(rest, each)
}

describe('useValidation', () => {
  let server: FakeServer
  let scope: EffectScope | null
  let draftIssues: ValidationIssue[]
  /** What `jobs/validate` answers; a function sees the request. */
  let answer: (request: Recorded) => unknown

  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    draftIssues = [CROP]
    answer = () => [CROP]
    server = new FakeServer()
      .on('POST /api/jobs/draft', () => sampleDraft(sampleJob(), draftIssues))
      .on('POST /api/presets/diff', [])
      .on('GET /api/presets/h265-mkv-1080p', samplePreset())
      .on('POST /api/jobs/validate', (request) => answer(request))
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    scope = null
  })

  afterEach(() => {
    scope?.stop()
    vi.useRealTimers()
  })

  function start(): void {
    scope = effectScope()
    scope.run(() => useValidation())
  }

  function validations(): Recorded[] {
    return server.requests.filter((request) => request.path === '/api/jobs/validate')
  }

  it("shows the draft's issues after open without asking the server", async () => {
    start()
    await opened()
    const validation = useValidationStore()
    expect(validation.issues).toEqual([CROP])
    expect(validation.pending).toBe(false)
    expect(validations()).toHaveLength(0)
  })

  it('is pending from the first edit and validates once, 250 ms after the last one', async () => {
    start()
    const editor = await opened()
    const validation = useValidationStore()
    answer = () => [issue('encoder.unavailable', 'video.encoder')]
    await inTurn([21, 20, 19, 18, 17], async (value) => {
      editor.set('/video/rate_control/value', value, { coalesce: 'quality' })
      expect(validation.pending).toBe(true)
      await vi.advanceTimersByTimeAsync(100)
    })
    expect(validations()).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE - 100 - 1)
    expect(validations()).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(1)
    expect(validations()).toHaveLength(1)
    expect(sentJob(validations()[0])).toEqual(JSON.parse(JSON.stringify(editor.job)))
    expect(validation.issues).toEqual([issue('encoder.unavailable', 'video.encoder')])
    expect(validation.pending).toBe(false)
  })

  it('never shows an answer for an older job over a newer one, and aborts the older request', async () => {
    start()
    const editor = await opened()
    const validation = useValidationStore()
    const older = deferred<unknown>()
    const signals: AbortSignal[] = []
    const fetch = server.fetch
    configureClient({
      fetch: async (input, init) => {
        // Only the validations: a presets/diff may go out in between.
        if (input instanceof Request && input.url.endsWith('/api/jobs/validate')) {
          signals.push(input.signal)
        }
        return fetch(input, init)
      },
    })
    answer = () => older.promise
    editor.set('/video/encoder', 'hevc_nvenc')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validations()).toHaveLength(1)

    answer = () => [issue('encoder.preset_unsupported', 'video.preset')]
    editor.set('/video/preset', 'p7')
    expect(signals.at(-1)?.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validation.issues).toEqual([issue('encoder.preset_unsupported', 'video.preset')])

    older.resolve([issue('encoder.unavailable', 'video.encoder')])
    await vi.advanceTimersByTimeAsync(0)
    expect(validation.issues).toEqual([issue('encoder.preset_unsupported', 'video.preset')])
  })

  it('stays pending until the answer for the job as it is now', async () => {
    start()
    const editor = await opened()
    const validation = useValidationStore()
    const first = deferred<unknown>()
    answer = () => first.promise
    editor.set('/video/preset', 'fast')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    const second = deferred<unknown>()
    answer = () => second.promise
    editor.set('/video/preset', 'medium')
    first.resolve([])
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validation.pending).toBe(true)
    second.resolve([])
    await vi.advanceTimersByTimeAsync(0)
    expect(validation.pending).toBe(false)
  })

  it('finds the issues of an answer by their path', async () => {
    start()
    const editor = await opened()
    const encoder = issue('encoder.unavailable', 'video.encoder')
    const bitrate = issue('audio.bitrate_out_of_range', 'audio[1].bitrate', 'info')
    answer = () => [bitrate, encoder]
    editor.set('/video/encoder', 'hevc_nvenc')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    const validation = useValidationStore()
    expect(validation.issuesFor('video.encoder')).toEqual([encoder])
    expect(validation.issuesFor('audio[1]', { nested: true })).toEqual([bitrate])
    expect(validation.issuesFor('audio[1]')).toEqual([])
  })

  it('clears the issues of a closed editor and drops its validation', async () => {
    start()
    const editor = await opened()
    const validation = useValidationStore()
    const late = deferred<unknown>()
    answer = () => late.promise
    editor.set('/video/preset', 'fast')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    editor.close()
    expect(validation.issues).toEqual([])
    expect(validation.pending).toBe(false)
    late.resolve([issue('encoder.unavailable', 'video.encoder')])
    await vi.advanceTimersByTimeAsync(0)
    expect(validation.issues).toEqual([])
  })

  it('clears the issues of the last job for a queued job and validates it at once', async () => {
    start()
    const editor = await opened()
    const validation = useValidationStore()
    vi.spyOn(useSourcesStore(), 'ensure').mockResolvedValue({
      id: 'queued',
      path: '/media/queued.mkv',
      source: null,
    })
    answer = () => new Promise(() => {})
    await editor.loadJob(sampleJob())
    expect(validation.issues).toEqual([])
    expect(validation.pending).toBe(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(validations()).toHaveLength(1)
  })

  it("keeps the draft's own issues while the job is the drafted one, without template fixes", async () => {
    const missing = issue('batch.track_missing', 'audio_rules[0]', 'error', [
      { label: 'Make the rule optional', patch: [], target: 'template' },
      { label: 'Overwrite', patch: [], target: 'settings' },
    ])
    draftIssues = [CROP, missing]
    start()
    const editor = await opened()
    const validation = useValidationStore()
    const shown = { ...missing, fixes: [{ label: 'Overwrite', patch: [], target: 'settings' }] }
    expect(validation.issues).toEqual([CROP, shown])

    validation.revalidate()
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validations()).toHaveLength(1)
    expect(validation.issues).toEqual([CROP, shown])

    editor.set('/video/preset', 'fast')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validation.issues).toEqual([CROP])

    editor.undo()
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validation.issues).toEqual([CROP, shown])
  })

  it('validates again when encoder statuses, tools or settings change', async () => {
    start()
    await opened()
    const system = useSystemStore()
    system.capabilities = { encoders: {} } as unknown as CapabilitySnapshot
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validations()).toHaveLength(1)
    system.info = { tools: {} } as unknown as typeof system.info
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validations()).toHaveLength(2)
    useSettingsStore().settings = { schema_version: 1 }
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validations()).toHaveLength(3)
  })

  it('keeps the issues of a failed validation and tries again when the connection is back', async () => {
    start()
    const editor = await opened()
    const validation = useValidationStore()
    const system = useSystemStore()
    system.connection = 'open'
    answer = () => problem(503, 'server.closing', 'The server is shutting down')
    editor.set('/video/preset', 'fast')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validation.pending).toBe(false)
    expect(validation.failed).toBe(true)
    expect(validation.issues).toEqual([CROP])

    answer = () => []
    system.connection = 'reconnecting'
    await vi.advanceTimersByTimeAsync(0)
    expect(validations()).toHaveLength(1)
    system.connection = 'open'
    await vi.advanceTimersByTimeAsync(0)
    expect(validations()).toHaveLength(2)
    expect(validation.failed).toBe(false)
    expect(validation.issues).toEqual([])
  })

  it('sends a validation that waits for its debounce at once on flush, and only once', async () => {
    start()
    const editor = await opened()
    const validation = useValidationStore()
    const held = deferred<unknown>()
    answer = () => held.promise
    editor.set('/video/preset', 'fast')
    validation.flush()
    await vi.advanceTimersByTimeAsync(0)
    expect(validations()).toHaveLength(1)
    validation.flush()
    held.resolve([])
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validations()).toHaveLength(1)
    expect(validation.pending).toBe(false)
  })

  it('asks again at once on flush after a failed validation, and only then', async () => {
    start()
    const editor = await opened()
    const validation = useValidationStore()
    validation.flush()
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validations()).toHaveLength(0)

    answer = () => problem(503, 'server.closing', 'The server is shutting down')
    editor.set('/video/preset', 'fast')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validation.failed).toBe(true)
    answer = () => []
    validation.flush()
    expect(validation.pending).toBe(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(validations()).toHaveLength(2)
    expect(validation.failed).toBe(false)
    expect(validation.pending).toBe(false)
  })

  it('shows a value the server cannot read as an error at its field', async () => {
    start()
    const editor = await opened()
    answer = () =>
      new Response(
        JSON.stringify({
          type: 'about:blank',
          title: 'The request is not valid',
          status: 422,
          code: 'request.invalid',
          errors: [
            {
              loc: ['body', 'job', 'video', 'rate_control', 'quality', 'value'],
              msg: 'Input should be a valid number',
              type: 'float_parsing',
            },
            {
              loc: ['body', 'job', 'audio', 0, 'bitrate'],
              msg: 'Input should be a valid integer',
              type: 'int_parsing',
            },
            { loc: ['body', 'job', 'video', 'encoder_id'], msg: 'Field required', type: 'missing' },
          ],
        }),
        { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
      )
    editor.set('/video/rate_control/value', 'abc')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    const validation = useValidationStore()
    expect(validation.issuesFor('video.rate_control.value')).toMatchObject([
      { severity: 'error', code: 'request.invalid', message: 'Input should be a valid number' },
    ])
    expect(validation.issuesFor('audio[0].bitrate')).toHaveLength(1)
    expect(validation.issuesFor('video.encoder_id')).toHaveLength(1)
    expect(validation.failed).toBe(false)
  })

  it('validates the open job at once when it starts, and stops with its scope', async () => {
    const editor = await opened()
    start()
    expect(useValidationStore().issues).toEqual([CROP])
    await vi.advanceTimersByTimeAsync(0)
    expect(validations()).toHaveLength(1)
    editor.set('/video/preset', 'fast')
    scope?.stop()
    expect(useValidationStore().pending).toBe(false)
    editor.set('/video/preset', 'medium')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    expect(validations()).toHaveLength(1)
  })

  it('keeps the issues of the same job when it starts again', async () => {
    start()
    const editor = await opened()
    answer = () => [issue('encoder.unavailable', 'video.encoder')]
    editor.set('/video/encoder', 'hevc_nvenc')
    await vi.advanceTimersByTimeAsync(EDIT_DEBOUNCE)
    scope?.stop()
    start()
    expect(useValidationStore().issues).toEqual([issue('encoder.unavailable', 'video.encoder')])
  })
})
