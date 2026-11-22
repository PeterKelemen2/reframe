import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, problem } from '@/api/testing/fakes'
import type { JobSettings, JobTypeInfo, MediaSource, ValidationIssue } from '@/api/types'
import { mountBase } from '@/components/base/testing'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'
import { useValidationStore } from '@/stores/validation'

import JobTypeCard from './JobTypeCard.vue'
import { multitrackSource } from './testing'

const SOON = { timeout: 2000, interval: 20 }

const ENCODE: JobTypeInfo = {
  job_type: 'encode',
  reason: 'Encode: the video is encoded with x265.',
  in_place_blockers: ['the video is encoded', 'audio track 1 (AC-3) is encoded'],
}
const METADATA_EDIT: JobTypeInfo = {
  job_type: 'metadata_edit',
  reason:
    'Metadata edit: only the track metadata changes, so Reframe edits multitrack.mkv in place, in seconds.',
  in_place_blockers: [],
}
const REMUX: JobTypeInfo = {
  job_type: 'remux',
  reason: 'Remux: the video and every audio and subtitle track are copied without re-encoding.',
  in_place_blockers: [],
}

const NOT_ALLOWED: ValidationIssue = {
  severity: 'error',
  code: 'inplace.not_allowed',
  path: 'output.edit_in_place',
  message: 'multitrack.mkv is in a folder that this server may only read.',
  fixes: [
    {
      label: 'Write a new file in /output',
      target: 'job',
      patch: [
        { op: 'replace', path: '/output/edit_in_place', value: false },
        { op: 'replace', path: '/output/path', value: '/output/multitrack.mkv' },
      ],
    },
  ],
}

let server: FakeServer
/** What `jobs/type` answers for the job it is sent. */
let typeOf: (job: JobSettings) => JobTypeInfo | Response | Promise<unknown>
const mounted: VueWrapper[] = []

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {}
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

/** The card for multitrack.mkv; `source`: the open source (`null`: not open in this window). */
async function mountCard(
  answer: typeof typeOf,
  { source = multitrackSource() as MediaSource | null } = {},
) {
  typeOf = answer
  server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(sampleJob()))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
    .on('POST /api/jobs/type', (request) => typeOf((request.body as { job: JobSettings }).job))
    .on('POST /api/jobs/draft-remux', (request) => {
      const { edit_in_place } = request.body as { edit_in_place: boolean }
      const job = sampleJob()
      job.video!.passthrough = true
      job.output!.edit_in_place = edit_in_place
      return { ...sampleDraft(job), decisions: [], subtitle_decisions: [] }
    })
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const wrapper = mountBase(JobTypeCard)
  mounted.push(wrapper)
  if (source !== null) {
    useSourcesStore().entries = [{ id: 'src', path: '/media/multitrack.mkv', source }]
  }
  const editor = useEditorStore()
  await editor.open('src')
  await vi.waitFor(() => expect(wrapper.find('[data-state="checking"]').exists()).toBe(false), SOON)
  return { wrapper, editor }
}

function text(wrapper: VueWrapper, selector: string): string {
  return wrapper.find(selector).text().replace(/\s+/g, ' ').trim()
}

function toggle(wrapper: VueWrapper) {
  return wrapper.find('[data-field="edit-in-place"] input')
}

async function answered(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, EDIT_DEBOUNCE + 20))
  await flushPromises()
}

describe('the Job type card', () => {
  it.each([
    [ENCODE, 'Encode'],
    [REMUX, 'Remux'],
    [METADATA_EDIT, 'Metadata edit'],
  ])('names the job type that jobs/type gives, and why: %s', async (answer, label) => {
    const { wrapper } = await mountCard(() => answer)
    expect(text(wrapper, '[data-field="job-type"]')).toBe(label)
    expect(text(wrapper, '[data-field="reason"]')).toBe(answer.reason)
  })

  it('shows why the job cannot edit its source in place before the switch is on', async () => {
    const { wrapper } = await mountCard(() => ENCODE)
    expect((toggle(wrapper).element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.findAll('[data-field="blocker"]').map((item) => item.text())).toEqual(
      ENCODE.in_place_blockers,
    )
    expect(wrapper.find('[data-state="can-edit-in-place"]').exists()).toBe(false)
  })

  it('offers Edit in place for a job that changes only metadata', async () => {
    const { wrapper } = await mountCard(() => REMUX)
    expect(text(wrapper, '[data-state="can-edit-in-place"]')).toContain('multitrack.mkv')
    expect(wrapper.find('[data-state="blocked"]').exists()).toBe(false)
  })

  it('turns Edit in place on and off, one undo step each, and asks for the type again', async () => {
    const { wrapper, editor } = await mountCard((job) =>
      job.output?.edit_in_place ? METADATA_EDIT : REMUX,
    )
    await toggle(wrapper).setValue(true)
    expect(editor.get('/output/edit_in_place')).toBe(true)
    await answered()
    expect(text(wrapper, '[data-field="job-type"]')).toBe('Metadata edit')
    await toggle(wrapper).setValue(false)
    expect(editor.get('/output/edit_in_place')).toBe(false)
    editor.undo()
    expect(editor.get('/output/edit_in_place')).toBe(true)
    editor.undo()
    expect(editor.get('/output/edit_in_place')).toBe(false)
    expect(editor.canUndo).toBe(false)
  })

  it('says plainly that the source itself is changed, and only while the switch is on', async () => {
    const { wrapper, editor } = await mountCard((job) =>
      job.output?.edit_in_place ? METADATA_EDIT : REMUX,
    )
    expect(wrapper.find('[data-state="in-place"]').exists()).toBe(false)
    editor.set('/output/edit_in_place', true)
    await answered()
    const notice = text(wrapper, '[data-state="in-place"]')
    expect(notice).toContain('/media/multitrack.mkv')
    expect(notice).toContain('the output name and folder are not used')
    // Off again: gone at once, before the answer about the new job comes.
    editor.set('/output/edit_in_place', false)
    await flushPromises()
    expect(wrapper.find('[data-state="in-place"]').exists()).toBe(false)
  })

  it('shows the in-place issues with their fixes, marks the switch, and applies a fix', async () => {
    const { wrapper, editor } = await mountCard(() => REMUX)
    editor.set('/output/edit_in_place', true)
    const other: ValidationIssue = {
      severity: 'warning',
      code: 'audio.bitrate_high',
      path: 'audio[0].bitrate',
      message: 'The bitrate is high.',
      fixes: [],
    }
    useValidationStore().issues = [NOT_ALLOWED, other]
    await flushPromises()
    expect(wrapper.findAll('.rf-issue__message').map((message) => message.text())).toEqual([
      NOT_ALLOWED.message,
    ])
    expect(wrapper.find('[data-field="edit-in-place"]').classes()).toContain('p-invalid')
    const fix = wrapper
      .findAll('.rf-issue__fix')
      .find((button) => button.text() === 'Write a new file in /output')
    await fix!.trigger('click')
    await flushPromises()
    expect(editor.get('/output/edit_in_place')).toBe(false)
    expect(editor.get('/output/path')).toBe('/output/multitrack.mkv')
  })

  const MP4 = { ...multitrackSource(), container: { format_name: 'mov,mp4,m4a,3gp,3g2,mj2' } }

  it.each([
    ['an MKV source, Edit in place off', multitrackSource(), false, false],
    ['an MKV source, Edit in place on', multitrackSource(), true, true],
    ['an MP4 source, Edit in place on', MP4, true, false],
    ['a source that is not open here, Edit in place on', null, true, false],
  ])(
    'drafts the remux-only job as one undo step, in place only when asked: %s',
    async (_name, source, switchOn, inPlace) => {
      const { wrapper, editor } = await mountCard(() => REMUX, {
        source: source as MediaSource | null,
      })
      if (switchOn) editor.set('/output/edit_in_place', true)
      await wrapper.find('[data-action="remux-only"]').trigger('click')
      await vi.waitFor(() => expect(editor.get('/video/passthrough')).toBe(true), SOON)
      const sent = server.requests.filter((request) => request.path === '/api/jobs/draft-remux')
      expect(sent.map((request) => request.body)).toEqual([
        { source_id: 'src', preset_id: 'h265-mkv-1080p', edit_in_place: inPlace },
      ])
      editor.undo()
      expect(editor.get('/video/passthrough')).toBe(false)
    },
  )

  it('says what Remux only writes: a new file, or the source itself with Edit in place', async () => {
    const { wrapper, editor } = await mountCard(() => REMUX)
    const help = () => text(wrapper, '[data-action="remux-only"] ~ p')
    expect(help()).toContain('into a new file')
    expect(help()).not.toContain('source file itself')
    editor.set('/output/edit_in_place', true)
    await flushPromises()
    expect(help()).toContain('the source file itself is edited')
  })

  it('keeps the focus on Remux only while the job is drafted', async () => {
    const { wrapper, editor } = await mountCard(() => REMUX)
    const late = deferred<unknown>()
    const remux = sampleJob()
    remux.video!.passthrough = true
    server.on('POST /api/jobs/draft-remux', () => late.promise)
    const button = wrapper.find<HTMLButtonElement>('[data-action="remux-only"]')
    button.element.focus()
    await button.trigger('click')
    expect(button.element.disabled).toBe(false)
    expect(button.attributes('aria-disabled')).toBe('true')
    expect(button.attributes('aria-busy')).toBe('true')
    late.resolve({ ...sampleDraft(remux), decisions: [], subtitle_decisions: [] })
    await vi.waitFor(() => expect(editor.get('/video/passthrough')).toBe(true), SOON)
    await flushPromises()
    expect(document.activeElement).toBe(button.element)
    expect(button.attributes('aria-busy')).toBeUndefined()
  })

  it('moves the focus to the switch when an in-place fix took its button away', async () => {
    const { wrapper, editor } = await mountCard(() => REMUX)
    editor.set('/output/edit_in_place', true)
    useValidationStore().issues = [NOT_ALLOWED]
    await flushPromises()
    const fix = wrapper.find<HTMLButtonElement>('.rf-issue__fix')
    fix.element.focus()
    await fix.trigger('click')
    await flushPromises()
    // The next validation answer has no in-place issue: the button goes with it.
    useValidationStore().issues = []
    await flushPromises()
    expect(document.activeElement).toBe(toggle(wrapper).element)
  })

  it('leaves the focus alone when it is elsewhere as an in-place issue goes', async () => {
    const { wrapper, editor } = await mountCard(() => REMUX)
    editor.set('/output/edit_in_place', true)
    useValidationStore().issues = [NOT_ALLOWED]
    await flushPromises()
    const fix = wrapper.find<HTMLButtonElement>('.rf-issue__fix')
    fix.element.focus()
    const remux = wrapper.find<HTMLButtonElement>('[data-action="remux-only"]')
    remux.element.focus()
    useValidationStore().issues = []
    await flushPromises()
    expect(document.activeElement).toBe(remux.element)
  })

  it('keeps the job and its button when the remux draft is refused', async () => {
    const { wrapper, editor } = await mountCard(() => REMUX)
    const refused = deferred<Response>()
    server.on('POST /api/jobs/draft-remux', () => refused.promise)
    const job = editor.job
    const button = wrapper.find('[data-action="remux-only"]')
    await button.trigger('click')
    expect(button.attributes('disabled')).toBeDefined()
    refused.resolve(problem(409, 'source.stale', 'The file changed or is gone since it was probed'))
    await flushPromises()
    expect(editor.job).toBe(job)
    expect(button.attributes('disabled')).toBeUndefined()
  })

  it('says why the type cannot be found, and that a newer answer is on its way', async () => {
    const { wrapper, editor } = await mountCard(() =>
      problem(422, 'probe.failed', 'The file cannot be read'),
    )
    expect(text(wrapper, '[data-state="failed"]')).toBe(
      'The job type cannot be found: The file cannot be read',
    )
    typeOf = () => new Promise(() => {})
    editor.set('/video/passthrough', true)
    await flushPromises()
    expect(wrapper.find('[data-state="updating"]').exists()).toBe(false)
    typeOf = () => ENCODE
    editor.set('/video/passthrough', false)
    await answered()
    typeOf = () => new Promise(() => {})
    editor.set('/video/passthrough', true)
    await flushPromises()
    expect(text(wrapper, '[data-state="updating"]')).toBe('Updating…')
    expect(text(wrapper, '[data-field="job-type"]')).toBe('Encode')
  })
})
