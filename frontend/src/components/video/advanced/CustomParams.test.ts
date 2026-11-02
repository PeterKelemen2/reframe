import { flushPromises, type VueWrapper } from '@vue/test-utils'
import InputText from 'primevue/inputtext'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { deferred, problem } from '@/api/testing/fakes'
import type { JobSettings, JobTemplate, ValidationIssue } from '@/api/types'
import { CHECK_DELAY } from '@/components/filters/useCustomCheck'
import { mountShell } from '@/components/shell/testing'
import { issue, sampleJob } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import { openJob, setUpVideo } from '../testing'
import CustomParams from './CustomParams.vue'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  vi.useRealTimers()
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

const refused: ValidationIssue = {
  severity: 'error',
  code: 'encoder.custom_param_rejected',
  path: 'video.custom_params',
  message: "FFmpeg refused 'nosuchparam': Unknown option: nosuchparam.",
}

async function mountParams(options: { text?: string; passthrough?: boolean } = {}) {
  const job = sampleJob()
  job.video = { ...job.video!, custom_params: options.text ?? '' }
  if (options.passthrough) job.video.passthrough = true
  const setup = setUpVideo({ job })
  setup.server.on('POST /api/jobs/dry-run', [])
  await openJob()
  vi.useFakeTimers()
  const { wrapper } = await mountShell(CustomParams, { pinia: setup.pinia })
  mounted.push(wrapper)
  return { ...setup, wrapper }
}

async function type(wrapper: VueWrapper, text: string) {
  wrapper.findComponent(InputText).vm.$emit('update:modelValue', text)
  await flushPromises()
}

async function afterCheckDelay() {
  await vi.advanceTimersByTimeAsync(CHECK_DELAY)
  await flushPromises()
}

function shownIssues(wrapper: VueWrapper): string[] {
  return wrapper.findAll('.rf-field__issue').map((item) => item.text())
}

function sentTexts(server: ReturnType<typeof setUpVideo>['server']): string[] {
  return server.requests
    .filter((request) => request.path === '/api/jobs/dry-run')
    .map((request) => (request.body as { job: JobSettings }).job.video?.custom_params ?? '')
}

describe('the custom parameters field', () => {
  it('dry-runs the newest text once the typing stops and shows FFmpeg’s refusal', async () => {
    const { wrapper, server, editor } = await mountParams()
    server.on('POST /api/jobs/dry-run', [refused])
    await type(wrapper, 'nosuch')
    await type(wrapper, 'nosuchparam=1')
    expect(editor.job?.video?.custom_params).toBe('nosuchparam=1')
    expect(wrapper.find('[data-check]').attributes('data-check')).toBe('checking')
    await vi.advanceTimersByTimeAsync(CHECK_DELAY - 1)
    expect(sentTexts(server)).toEqual([])
    await afterCheckDelay()
    expect(sentTexts(server)).toEqual(['nosuchparam=1'])
    expect(shownIssues(wrapper).join()).toContain("FFmpeg refused 'nosuchparam'")
    expect(wrapper.find('.custom-params').classes()).toContain('rf-field--error')
  })

  it('tells a screen reader the refusal in the status line that said it was checking', async () => {
    const { wrapper, server } = await mountParams()
    server.on('POST /api/jobs/dry-run', [refused])
    await type(wrapper, 'nosuchparam=1')
    const status = wrapper.find('[role="status"]').element
    expect(status.textContent).toContain('Checking with a one-frame test')
    await afterCheckDelay()
    expect(status.isConnected).toBe(true)
    expect(status.getAttribute('aria-live') ?? 'polite').toBe('polite')
    expect(status.textContent?.trim()).toBe(refused.message)
  })

  it('shows only the answer for the newest text', async () => {
    const { wrapper, server } = await mountParams()
    const first = deferred<ValidationIssue[]>()
    const second = deferred<ValidationIssue[]>()
    const answers = [first, second]
    server.on('POST /api/jobs/dry-run', () => answers.shift()?.promise)
    await type(wrapper, 'nosuchparam=1')
    await afterCheckDelay()
    await type(wrapper, 'psy-rd=2.0')
    await afterCheckDelay()
    second.resolve([])
    await flushPromises()
    first.resolve([refused])
    await flushPromises()
    expect(sentTexts(server)).toEqual(['nosuchparam=1', 'psy-rd=2.0'])
    expect(shownIssues(wrapper)).toEqual([])
    expect(wrapper.find('[data-check]').attributes('data-check')).toBe('accepted')
  })

  it('makes one undo step of a typing run', async () => {
    const { wrapper, editor } = await mountParams({ text: 'rect=0' })
    await type(wrapper, 'rect=0:')
    await type(wrapper, 'rect=0:amp=1')
    editor.undo()
    expect(editor.job?.video?.custom_params).toBe('rect=0')
    expect(editor.canUndo).toBe(false)
  })

  it('shows validation’s file rule once, with the dry run’s issues about the parameters', async () => {
    const { wrapper, server } = await mountParams()
    const fileRule = issue('encoder.custom_param_file', 'video.custom_params')
    useValidationStore().issues = [fileRule]
    const testEncode = issue('encoder.dry_run_failed', 'video.encoder')
    const elsewhere = issue('encoder.dry_run_failed', 'filters.custom.custom')
    server.on('POST /api/jobs/dry-run', [fileRule, testEncode, elsewhere])
    await type(wrapper, 'csv=out.csv:me=foo')
    await afterCheckDelay()
    expect(shownIssues(wrapper)).toEqual([
      expect.stringContaining(fileRule.message),
      expect.stringContaining(testEncode.message),
    ])
  })

  it('checks the text the field opens with, and again for another job', async () => {
    const { server } = await mountParams({ text: 'rect=0' })
    await afterCheckDelay()
    expect(sentTexts(server)).toEqual(['rect=0'])
    await useEditorStore().open('source-1')
    await afterCheckDelay()
    expect(sentTexts(server)).toEqual(['rect=0', 'rect=0'])
  })

  it('drops the answer for the job that was open before', async () => {
    const { wrapper, server } = await mountParams({ text: 'nosuchparam=1' })
    const old = deferred<ValidationIssue[]>()
    server.on('POST /api/jobs/dry-run', () => old.promise)
    await afterCheckDelay()
    server.on('POST /api/jobs/dry-run', [])
    await useEditorStore().open('source-1')
    old.resolve([refused])
    await flushPromises()
    expect(shownIssues(wrapper)).toEqual([])
    await afterCheckDelay()
    expect(wrapper.find('[data-check]').attributes('data-check')).toBe('accepted')
  })

  it('drops the answer for the encoder that was set before, and checks with the new one', async () => {
    const { wrapper, server, editor } = await mountParams({ text: 'nosuchparam=1' })
    const old = deferred<ValidationIssue[]>()
    server.on('POST /api/jobs/dry-run', () => old.promise)
    await afterCheckDelay()
    server.on('POST /api/jobs/dry-run', [])
    editor.set('/video/encoder', 'libsvtav1')
    old.resolve([refused])
    await flushPromises()
    expect(shownIssues(wrapper)).toEqual([])
    await afterCheckDelay()
    const encoders = server.requests
      .filter((request) => request.path === '/api/jobs/dry-run')
      .map((request) => (request.body as { job: JobSettings }).job.video?.encoder)
    expect(encoders).toEqual(['libx265', 'libsvtav1'])
    expect(wrapper.find('[data-check]').attributes('data-check')).toBe('accepted')
  })

  it('drops the answer for the group’s file shown before, and checks the one shown now', async () => {
    const { wrapper, server, editor } = await mountParams({ text: 'nosuchparam=1' })
    const job = editor.job!
    const group = {
      kind: 'group' as const,
      groupId: 'g1',
      job,
      template: { job } as unknown as JobTemplate,
      presetId: null,
      overrides: {},
      scope: 'group' as const,
    }
    editor.target = { ...group, sourceId: 'e01' }
    const old = deferred<ValidationIssue[]>()
    server.on('POST /api/jobs/dry-run', () => old.promise)
    await afterCheckDelay()
    server.on('POST /api/jobs/dry-run', [])
    editor.target = { ...group, sourceId: 'e02', job: structuredClone(job) }
    old.resolve([refused])
    await flushPromises()
    expect(shownIssues(wrapper)).toEqual([])
    await afterCheckDelay()
    expect(sentTexts(server)).toHaveLength(2)
    expect(wrapper.find('[data-check]').attributes('data-check')).toBe('accepted')
  })

  it('checks nothing without a text', async () => {
    const { wrapper, server } = await mountParams({ text: 'rect=0' })
    await type(wrapper, '')
    await afterCheckDelay()
    expect(sentTexts(server)).toEqual([])
    expect(wrapper.find('[role="status"]').text()).toBe('')
  })

  it('says why the test encode did not run', async () => {
    const { wrapper, server } = await mountParams()
    server.on('POST /api/jobs/dry-run', () =>
      problem(422, 'jobs.invalid', 'The job has errors', 'out.mkv is outside the output folders'),
    )
    await type(wrapper, 'psy-rd=2.0')
    await afterCheckDelay()
    const reason = 'The one-frame test did not run: out.mkv is outside the output folders'
    expect(shownIssues(wrapper)).toEqual([expect.stringContaining(reason)])
    expect(wrapper.find('[role="status"]').text()).toBe(reason)
  })

  it('takes the focus into its text when revealed', async () => {
    Element.prototype.scrollIntoView = vi.fn<() => void>()
    const { wrapper } = await mountParams({ text: 'csv=out.csv' })
    useUiStore().reveal('video.custom_params')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.find('input').element)
  })

  it('cannot be edited while the video is passed through', async () => {
    const { wrapper } = await mountParams({ passthrough: true })
    expect(wrapper.find('input').attributes('disabled')).toBeDefined()
  })
})
