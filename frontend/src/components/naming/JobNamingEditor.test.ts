import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, type Recorded } from '@/api/testing/fakes'
import type { JobNaming, JobSettings, NameResult } from '@/api/types'
import { mountBase } from '@/components/base/testing'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { platform } from '@/platform'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useToastStore } from '@/stores/toasts'

import JobNamingEditor from './JobNamingEditor.vue'
import { PREVIEW_DEBOUNCE } from './preview'
import { hacksawResult, stubDom, unknownVariable, VARIABLES } from './testing/samples'

vi.mock('@/platform', () => ({
  platform: { pickFolder: vi.fn<(opts?: { title?: string }) => Promise<string | null>>() },
}))

stubDom()

const ROUTE = 'POST /api/naming/preview'

interface PreviewBody {
  source_ids: string[]
  job: JobSettings
}

/** A server that names the file from the template, with `{main_title}` and the `name` override. */
function named(job: JobSettings): NameResult {
  const given = job.output?.naming as JobNaming
  const title = given.field_overrides?.name ?? 'Hacksaw.Ridge'
  const stem =
    given.mode === 'manual'
      ? (given.manual_name ?? '')
      : (given.template ?? '{main_title}').replace('{main_title}', title)
  const relative = `${stem}.${job.output?.container ?? 'mkv'}`
  const issues = given.template?.includes('titel') ? [unknownVariable(given.template)] : []
  return hacksawResult({
    template: given.template ?? '{main_title}',
    relative_path: relative,
    path: `/output/${relative}`,
    issues,
  })
}

function draftedJob(): JobSettings {
  const job = sampleJob()
  job.output!.path = '/output/Hacksaw.Ridge.mkv'
  return job
}

let server: FakeServer
let pinia: Pinia

function previews(): PreviewBody[] {
  return server.requests
    .filter((request: Recorded) => `${request.method} ${request.path}` === ROUTE)
    .map((request) => request.body as PreviewBody)
}

async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
  await flushPromises()
}

async function mountOpened() {
  const editor = useEditorStore()
  await editor.open('src')
  await flushPromises()
  const wrapper = mountBase(JobNamingEditor, { pinia })
  useSystemStore().namingVariables = VARIABLES
  await flushPromises()
  return { editor, wrapper }
}

function naming(editor: ReturnType<typeof useEditorStore>): JobNaming | undefined {
  return editor.job?.output?.naming
}

beforeEach(() => {
  vi.useFakeTimers()
  pinia = createPinia()
  setActivePinia(pinia)
  server = new FakeServer()
    .on('POST /api/jobs/draft', () => ({ ...sampleDraft(draftedJob()), naming: hacksawResult() }))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
    .on(ROUTE, (request) => [named((request.body as PreviewBody).job)])
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  vi.useRealTimers()
  vi.mocked(platform.pickFolder).mockReset()
  document.body.innerHTML = ''
})

describe('JobNamingEditor', () => {
  it("shows the draft's name, path and name source with its reason without asking the server again", async () => {
    const { wrapper } = await mountOpened()
    await settle()
    expect(previews()).toHaveLength(0)
    expect(wrapper.get('[data-testid="naming-result"]').text()).toBe('Hacksaw.Ridge.mkv')
    expect(wrapper.get('[data-testid="job-path"]').text()).toBe('/output/Hacksaw.Ridge.mkv')
    expect(wrapper.get('[data-testid="name-reason"]').text()).toBe(hacksawResult().reason)
    expect((wrapper.get('input[role="combobox"]').element as HTMLInputElement).value).toBe(
      '{main_title}',
    )
  })

  it('previews a typed template after a pause, then puts the name and the path into the job as one undo step', async () => {
    const { editor, wrapper } = await mountOpened()
    const before = structuredClone(editor.job)
    const input = wrapper.get('input[role="combobox"]')
    await input.setValue('{main_title}.x')
    await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE - 50)
    await input.setValue('{main_title}.x2')
    await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE - 50)
    expect(previews()).toHaveLength(0)
    expect(naming(editor)?.template).toBeNull()
    await settle()

    expect(previews()).toHaveLength(1)
    expect(previews()[0]).toMatchObject({
      source_ids: ['src'],
      job: { output: { naming: { template: '{main_title}.x2' } } },
    })
    expect(naming(editor)?.template).toBe('{main_title}.x2')
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.x2.mkv')
    expect(wrapper.get('[data-testid="naming-result"]').text()).toBe('Hacksaw.Ridge.x2.mkv')

    editor.undo()
    expect(editor.job).toEqual(before)
  })

  it('keeps typing in one field one undo step until the field loses the focus', async () => {
    const { editor, wrapper } = await mountOpened()
    const before = structuredClone(editor.job)
    const input = wrapper.get('input[role="combobox"]')
    await input.setValue('{main_title}.a')
    await settle()
    await input.setValue('{main_title}.ab')
    await settle()
    await input.trigger('blur')
    await input.setValue('{main_title}.abc')
    await settle()

    editor.undo()
    expect(naming(editor)?.template).toBe('{main_title}.ab')
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.ab.mkv')
    editor.undo()
    expect(editor.job).toEqual(before)
  })

  it('previews an edit at once when its field loses the focus, and puts it into the job with its path, ending its undo step', async () => {
    const { editor, wrapper } = await mountOpened()
    const before = structuredClone(editor.job)
    const input = wrapper.get('input[role="combobox"]')
    await input.setValue('{main_title}.now')
    await input.trigger('blur')
    // Not without its path: the job never has a naming and a path that do not belong together.
    expect(naming(editor)?.template).toBeNull()
    expect(editor.editing).toBe(true)
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(naming(editor)?.template).toBe('{main_title}.now')
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.now.mkv')
    expect(editor.editing).toBe(false)

    // The step ended with the path: the next typing is a step of its own.
    await input.setValue('{main_title}.later')
    await settle()
    editor.undo()
    expect(naming(editor)?.template).toBe('{main_title}.now')
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.now.mkv')
    editor.undo()
    expect(editor.job).toEqual(before)
  })

  it('keeps the folder chosen for the job when the name changes', async () => {
    const { editor, wrapper } = await mountOpened()
    editor.set('/output/path', '/picked/Hacksaw.Ridge.mkv')
    await settle()
    await wrapper.get('input[role="combobox"]').setValue('{main_title}.y')
    await settle()
    expect(editor.job?.output?.path).toBe('/picked/Hacksaw.Ridge.y.mkv')
    expect(wrapper.get('[data-testid="job-folder"]').text()).toBe('/picked')
  })

  it('previews a per-file field override and keeps it in the job', async () => {
    const { editor, wrapper } = await mountOpened()
    await wrapper.get('input[data-field="name"]').setValue('My Movie')
    await settle()
    expect(previews().at(-1)?.job.output?.naming?.field_overrides).toEqual({ name: 'My Movie' })
    expect(wrapper.get('[data-testid="naming-result"]').text()).toBe('My Movie.mkv')
    expect(naming(editor)?.field_overrides).toEqual({ name: 'My Movie' })
    expect(editor.job?.output?.path).toBe('/output/My Movie.mkv')
  })

  it('does not let an answer for an older job undo a change made meanwhile', async () => {
    const slow = deferred<NameResult[]>()
    server.on(ROUTE, (request) =>
      previews().length === 1 ? slow.promise : [named((request.body as PreviewBody).job)],
    )
    const { editor, wrapper } = await mountOpened()
    await wrapper.get('input[role="combobox"]').setValue('{main_title}.z')
    await settle()
    editor.set('/output/container', 'mp4')
    await settle()
    slow.resolve([hacksawResult({ relative_path: 'stale.mkv', path: '/output/stale.mkv' })])
    await flushPromises()

    expect(editor.job?.output?.container).toBe('mp4')
    expect(naming(editor)?.template).toBe('{main_title}.z')
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.z.mp4')
  })

  it("brings the job's naming back into the fields after an undo elsewhere", async () => {
    const { editor, wrapper } = await mountOpened()
    const input = wrapper.get('input[role="combobox"]')
    await input.setValue('{main_title}.u')
    await settle()
    editor.undo()
    await settle()
    expect((input.element as HTMLInputElement).value).toBe('{main_title}')
    expect(wrapper.get('[data-testid="naming-result"]').text()).toBe('Hacksaw.Ridge.mkv')
  })

  it('keeps an edit whose preview failed in the field and out of the job, says why, and sends it again when asked', async () => {
    const { editor, wrapper } = await mountOpened()
    server.on(ROUTE, () => new Response('{}', { status: 500 }))
    const input = wrapper.get('input[role="combobox"]')
    await input.setValue('{name}')
    await settle()
    expect(naming(editor)?.template).toBeNull()
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.mkv')
    expect((input.element as HTMLInputElement).value).toBe('{name}')
    expect(wrapper.get('[role="alert"]').text()).toMatch(/^No preview: /)
    expect(editor.editing).toBe(false)
    expect(editor.editFailure).not.toBeNull()

    server.on(ROUTE, (request) => [named((request.body as PreviewBody).job)])
    editor.flushEdits()
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(naming(editor)?.template).toBe('{name}')
    expect(editor.job?.output?.path).toBe('/output/{name}.mkv')
    expect(editor.editFailure).toBeNull()
  })

  it.each([
    [
      'Use the preset’s template',
      '[data-action="reset-template"]',
      { template: null },
      '/output/Hacksaw.Ridge.mkv',
    ],
    [
      'Manual name',
      '[data-option="mode"] button:nth-child(2)',
      { mode: 'manual', manual_name: 'Hacksaw.Ridge.c' },
      '/output/Hacksaw.Ridge.c.mkv',
    ],
  ])(
    'holds a change made without typing (%s) as an edit on its way until it is in the job, and sends it at once when asked',
    async (_, selector, expected, path) => {
      const { editor, wrapper } = await mountOpened()
      await wrapper.get('input[role="combobox"]').setValue('{main_title}.c')
      await settle()
      expect(editor.editing).toBe(false)

      await wrapper.get(selector).trigger('click')
      expect(editor.editing).toBe(true)
      expect(naming(editor)?.template).toBe('{main_title}.c')
      editor.flushEdits()
      await vi.advanceTimersByTimeAsync(0)
      await flushPromises()
      expect(naming(editor)).toMatchObject(expected)
      expect(editor.job?.output?.path).toBe(path)
      expect(editor.editing).toBe(false)
    },
  )

  it('keeps the naming and its path in one undo step when another edit comes before the preview answers', async () => {
    const { editor, wrapper } = await mountOpened()
    const input = wrapper.get('input[role="combobox"]')
    await input.setValue('{main_title}.q')
    await input.trigger('blur')
    editor.set('/video/rate_control/value', 30)
    await settle()
    expect(naming(editor)?.template).toBe('{main_title}.q')
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.q.mkv')

    editor.undo()
    expect(naming(editor)?.template).toBeNull()
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.mkv')
    expect(editor.job?.video?.rate_control).toEqual({ mode: 'quality', value: 30 })
  })

  it('puts an edit on its way into the job with its path when the editor unmounts before the answer', async () => {
    const { editor, wrapper } = await mountOpened()
    const before = structuredClone(editor.job)
    await wrapper.get('input[role="combobox"]').setValue('{main_title}.left')
    wrapper.unmount()
    expect(editor.editing).toBe(true)
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()

    expect(naming(editor)?.template).toBe('{main_title}.left')
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.left.mkv')
    expect(editor.editing).toBe(false)
    editor.undo()
    expect(editor.job).toEqual(before)
  })

  it('names the job as it is when it changed after the editor unmounted', async () => {
    const slow = deferred<NameResult[]>()
    const { editor, wrapper } = await mountOpened()
    server.on(ROUTE, (request) =>
      previews().length === 1 ? slow.promise : [named((request.body as PreviewBody).job)],
    )
    await wrapper.get('input[role="combobox"]').setValue('{main_title}.late')
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(0)
    editor.set('/output/container', 'mp4')
    slow.resolve([hacksawResult({ relative_path: 'stale.mkv', path: '/output/stale.mkv' })])
    await flushPromises()
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()

    expect(previews()).toHaveLength(2)
    expect(naming(editor)?.template).toBe('{main_title}.late')
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.late.mp4')
  })

  it('drops an edit of an unmounted editor whose preview failed, and says so', async () => {
    const { editor, wrapper } = await mountOpened()
    server.on(ROUTE, () => new Response('{}', { status: 500 }))
    await wrapper.get('input[role="combobox"]').setValue('{main_title}.x')
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(naming(editor)?.template).toBeNull()
    expect(editor.editing).toBe(false)
    expect(editor.editFailure).toBeNull()
    expect(useToastStore().items.map((item) => item.summary)).toEqual([
      'The output name was not changed',
    ])
  })

  it('names the name-source list by its label', async () => {
    const { wrapper } = await mountOpened()
    const combobox = wrapper.get('[data-option="name_source"] [role="combobox"]')
    const label = document.getElementById(combobox.attributes('aria-labelledby') ?? '')
    expect(label?.textContent).toBe('Name source')
  })

  it("shows a template error at the field and puts its fix into the job's template", async () => {
    const { editor, wrapper } = await mountOpened()
    await wrapper.get('input[role="combobox"]').setValue('{main_titel}')
    await settle()
    const field = wrapper.get('[data-path="output.naming.template"]')
    expect(field.text()).toContain('Unknown variable {main_titel}')
    await field
      .findAll('button')
      .find((button) => button.text() === 'Use {main_title}')
      ?.trigger('click')
    await settle()
    expect(naming(editor)?.template).toBe('{main_title}')
  })

  it("offers the path the naming gives after another change made the job's path stale", async () => {
    const { editor, wrapper } = await mountOpened()
    editor.set('/output/container', 'mp4')
    await settle()
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.mkv')
    await wrapper.get('[data-action="update-path"]').trigger('click')
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.mp4')
    await settle()
    expect(wrapper.find('[data-testid="stale-path"]').exists()).toBe(false)
  })

  it('names the job by hand, starting from the name it has', async () => {
    const { editor, wrapper } = await mountOpened()
    await wrapper.get('[data-option="mode"]').findAll('button')[1]?.trigger('click')
    await settle()
    expect(naming(editor)).toMatchObject({ mode: 'manual', manual_name: 'Hacksaw.Ridge' })
    await wrapper.get('[data-option="manual_name"]').setValue('Mine')
    await settle()
    expect(editor.job?.output?.path).toBe('/output/Mine.mkv')
  })

  it('moves the job into a picked folder as one undo step', async () => {
    vi.mocked(platform.pickFolder).mockResolvedValue('/picked')
    const { editor, wrapper } = await mountOpened()
    await wrapper.get('[data-action="choose-folder"]').trigger('click')
    await flushPromises()
    expect(editor.job?.output?.path).toBe('/picked/Hacksaw.Ridge.mkv')
    editor.undo()
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.mkv')
  })

  it('says so when no folder can be picked and keeps the path', async () => {
    vi.mocked(platform.pickFolder).mockRejectedValue(new Error('not available'))
    const { editor, wrapper } = await mountOpened()
    await wrapper.get('[data-action="choose-folder"]').trigger('click')
    await flushPromises()
    expect(useToastStore().items).toHaveLength(1)
    expect(editor.job?.output?.path).toBe('/output/Hacksaw.Ridge.mkv')
  })

  it('asks the server for the name of a job that has no draft', async () => {
    const editor = useEditorStore()
    await editor.open('src')
    await flushPromises()
    editor.draft = null
    editor.target = { kind: 'job', sourceId: 'src', job: Object.freeze(draftedJob()) }
    const wrapper = mountBase(JobNamingEditor, { pinia })
    await vi.advanceTimersByTimeAsync(0)
    await flushPromises()
    expect(previews()).toHaveLength(1)
    expect(wrapper.get('[data-testid="naming-result"]').text()).toBe('Hacksaw.Ridge.mkv')
  })
})
