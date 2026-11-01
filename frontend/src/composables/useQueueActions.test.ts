import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, defineComponent, reactive, ref, toRefs } from 'vue'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, problem, settle } from '@/api/testing/fakes'
import type { JobSettings, QueueJob, SourceEntry, ValidationIssue } from '@/api/types'
import type { EditorTarget } from '@/stores/editor'
import { createAppI18n } from '@/i18n'
import { useQueueStore } from '@/stores/queue'
import { useToastStore } from '@/stores/toasts'

import { type QueueActions, useQueueActions } from './useQueueActions'

// Test doubles of the editor, validation and sources stores: the members their contracts give.
const editorState = reactive({
  target: null as EditorTarget | null,
  presetId: null as string | null,
  loading: false,
  session: 1,
  editing: false,
  editFailure: null as string | null,
})
const editor = reactive({
  ...toRefs(editorState),
  job: computed((): JobSettings | null =>
    editorState.target?.kind === 'job' ? editorState.target.job : null,
  ),
  flushEdits: vi.fn<() => void>(),
})
const issues = ref<ValidationIssue[]>([])
const validation = reactive({
  issues,
  pending: false,
  failed: false,
  hasErrors: computed(() => issues.value.some((found) => found.severity === 'error')),
  flush: vi.fn<() => void>(),
})
const sources = reactive({ entries: [] as SourceEntry[] })
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
vi.mock('@/stores/validation', () => ({ useValidationStore: () => validation }))
vi.mock('@/stores/sources', () => ({ useSourcesStore: () => sources }))

function settings(path: string, output: string | null = `/out/${path}.mkv`): JobSettings {
  return {
    schema_version: 1,
    source: { path: `/media/${path}.mkv` },
    output: output === null ? undefined : { path: output },
  } as JobSettings
}

function entry(id: string): SourceEntry {
  return { id, path: `/media/${id}.mkv`, source: null }
}

function issue(severity: ValidationIssue['severity'], message: string): ValidationIssue {
  return { severity, code: 'test', path: 'video.encoder', message }
}

function queued(job: JobSettings, extra: Partial<QueueJob> = {}): QueueJob {
  return {
    id: `job-${job.source.path}`,
    position: 0,
    state: 'waiting',
    settings: job,
    created_at: '2026-10-29T10:00:00Z',
    ...extra,
  } as QueueJob
}

function open(sourceId: string, job: JobSettings): void {
  editor.target = { kind: 'job', sourceId, job }
}

let server: FakeServer

function actions(): QueueActions {
  let result: QueueActions | undefined
  const Host = defineComponent({
    setup() {
      result = useQueueActions()
      return () => null
    },
  })
  mount(Host, { global: { plugins: [createAppI18n()] } })
  return result as QueueActions
}

function toasts() {
  return useToastStore().items.map(({ severity, summary, detail }) => ({
    severity,
    summary,
    detail,
  }))
}

function queueBodies(): JobSettings[][] {
  return server.requests
    .filter((request) => request.method === 'POST' && request.path === '/api/queue')
    .map((request) => (request.body as { jobs: JobSettings[] }).jobs)
}

beforeEach(() => {
  setActivePinia(createPinia())
  editor.target = null
  editor.presetId = null
  editor.loading = false
  editor.session = 1
  editor.editing = false
  editor.editFailure = null
  editor.flushEdits.mockReset()
  validation.issues = []
  validation.pending = false
  validation.failed = false
  validation.flush.mockReset()
  sources.entries = []
  server = new FakeServer()
    .on('GET /api/queue', { jobs: [] })
    .on('GET /api/power', { pending: null })
    .on('GET /api/settings', { schema_version: 1 })
    .on('POST /api/queue', (request) =>
      (request.body as { jobs: JobSettings[] }).jobs.map((job) => queued(job)),
    )
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  vi.restoreAllMocks()
  document.body.replaceChildren()
})

describe('canAdd', () => {
  it.each([
    ['no job is open', () => {}, false],
    ['the job is fine', () => open('s1', settings('a')), true],
    [
      'the job has an error',
      () => {
        open('s1', settings('a'))
        validation.issues = [issue('error', 'broken')]
      },
      false,
    ],
    [
      'the job has only a warning',
      () => {
        open('s1', settings('a'))
        validation.issues = [issue('warning', 'hm')]
      },
      true,
    ],
    // The add waits for these: the button must not turn off under a click that blurs a field.
    [
      'a validation is pending',
      () => {
        open('s1', settings('a'))
        validation.pending = true
      },
      true,
    ],
    [
      'an edit is on its way into the job',
      () => {
        open('s1', settings('a'))
        editor.editing = true
      },
      true,
    ],
    [
      'the editor is loading a draft',
      () => {
        open('s1', settings('a'))
        editor.loading = true
      },
      false,
    ],
    ['the job has no output path', () => open('s1', settings('a', null)), false],
  ])('when %s: %s', (_, arrange, expected) => {
    arrange()
    expect(actions().canAdd.value).toBe(expected)
  })
})

describe('addCurrent', () => {
  it("sends the editor's job to the end of the queue and says so", async () => {
    const job = settings('a')
    open('s1', job)
    await actions().addCurrent()

    expect(queueBodies()).toEqual([[job]])
    expect(useQueueStore().jobs.map((queuedJob) => queuedJob.settings.source.path)).toEqual([
      '/media/a.mkv',
    ])
    expect(toasts()).toEqual([
      { severity: 'success', summary: 'Added to the queue', detail: 'a.mkv' },
    ])
  })

  it('adds nothing while the job has an error, and says why', async () => {
    open('s1', settings('a'))
    validation.issues = [issue('error', 'The encoder is not available.')]
    await actions().addCurrent()
    expect(queueBodies()).toEqual([])
    expect(toasts()).toEqual([
      {
        severity: 'warn',
        summary: 'Not added to the queue: the job has an error',
        detail: 'The encoder is not available.',
      },
    ])
  })

  it('puts the value typed into the focused field into the job first, and gives the field the focus back', async () => {
    open('s1', settings('a'))
    // A field that writes into the job only when it loses the focus (PrimeVue's InputNumber).
    const field = document.createElement('input')
    field.type = 'text'
    document.body.append(field)
    field.addEventListener('blur', () => open('s1', settings('a', '/out/typed.mkv')))
    field.focus()

    await actions().addCurrent()

    expect(queueBodies()).toEqual([[settings('a', '/out/typed.mkv')]])
    expect(document.activeElement).toBe(field)
  })

  it('waits for the check of the job on its way, asks for it at once, and adds the job as it then is', async () => {
    open('s1', settings('a'))
    validation.pending = true
    const adding = actions().addCurrent()
    await settle()
    expect(validation.flush).toHaveBeenCalled()
    expect(queueBodies()).toEqual([])

    open('s1', settings('a', '/out/later.mkv'))
    validation.pending = false
    await adding
    expect(queueBodies()).toEqual([[settings('a', '/out/later.mkv')]])
  })

  it('waits for an edit on its way (sent at once), then for the check of the job with it', async () => {
    open('s1', settings('a'))
    editor.editing = true
    const adding = actions().addCurrent()
    await settle()
    expect(editor.flushEdits).toHaveBeenCalledTimes(1)

    // The edit lands: the job changes and its check starts in the same change.
    open('s1', settings('a', '/out/renamed.mkv'))
    editor.editing = false
    validation.pending = true
    await settle()
    expect(queueBodies()).toEqual([])

    validation.pending = false
    await adding
    expect(queueBodies()).toEqual([[settings('a', '/out/renamed.mkv')]])
  })

  it('does not add a job whose check, once it answers, has an error', async () => {
    open('s1', settings('a'))
    validation.pending = true
    const adding = actions().addCurrent()
    await settle()
    validation.issues = [issue('error', 'The quality is out of range.')]
    validation.pending = false
    await adding
    expect(queueBodies()).toEqual([])
    expect(toasts().map((toast) => toast.detail)).toEqual(['The quality is out of range.'])
  })

  it('asks once more after a failed check, and adds the job when that answer has no error', async () => {
    open('s1', settings('a'))
    validation.failed = true
    validation.flush.mockImplementation(() => {
      validation.pending = true
    })
    const adding = actions().addCurrent()
    await settle()
    expect(validation.flush).toHaveBeenCalled()
    expect(queueBodies()).toEqual([])
    validation.failed = false
    validation.pending = false
    await adding
    expect(queueBodies()).toEqual([[settings('a')]])
  })

  it('adds nothing when the check fails again, and says so', async () => {
    open('s1', settings('a'))
    validation.failed = true
    validation.flush.mockImplementation(() => {
      validation.pending = true
    })
    const adding = actions().addCurrent()
    await settle()
    validation.pending = false
    await adding
    expect(queueBodies()).toEqual([])
    expect(toasts()).toEqual([
      {
        severity: 'warn',
        summary: 'Not added to the queue',
        detail:
          'The job could not be checked, so it was not added. Try again when the server answers.',
      },
    ])
  })

  it('adds nothing when an edit on the screen could not reach the job, and says why', async () => {
    open('s1', settings('a'))
    editor.editFailure = 'The server did not answer.'
    await actions().addCurrent()
    expect(editor.flushEdits).toHaveBeenCalled()
    expect(queueBodies()).toEqual([])
    expect(toasts().map((toast) => toast.detail)).toEqual([
      'The output name could not be updated: The server did not answer.',
    ])
  })

  it('gives up after a while when the check does not answer, and says it is still being checked', async () => {
    vi.useFakeTimers()
    try {
      open('s1', settings('a'))
      validation.pending = true
      const adding = actions().addCurrent()
      await vi.advanceTimersByTimeAsync(19_000)
      expect(toasts()).toEqual([])
      await vi.advanceTimersByTimeAsync(1_000)
      await adding
      expect(queueBodies()).toEqual([])
      expect(toasts().map((toast) => toast.detail)).toEqual([
        'The job is still being checked. Try again in a moment.',
      ])
      expect(actions().canAdd.value).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('adds nothing, and says nothing, when another job is opened while it waits', async () => {
    open('s1', settings('a'))
    validation.pending = true
    const adding = actions().addCurrent()
    await settle()
    open('s2', settings('b'))
    editor.session = 2
    await adding
    validation.pending = false
    await settle()
    expect(queueBodies()).toEqual([])
    expect(toasts()).toEqual([])
  })

  it('reports a job that the queue took as failed', async () => {
    server.on('POST /api/queue', (request) =>
      (request.body as { jobs: JobSettings[] }).jobs.map((job) =>
        queued(job, { state: 'failed', error: 'Another job writes /out/a.mkv' }),
      ),
    )
    open('s1', settings('a'))
    await actions().addCurrent()
    expect(toasts()).toEqual([
      {
        severity: 'error',
        summary: 'The job was added as failed',
        detail: 'Another job writes /out/a.mkv',
      },
    ])
  })

  it('adds once while an add is under way, and can add again after a refused one', async () => {
    const answer = deferred<Response>()
    server.on('POST /api/queue', () => answer.promise)
    open('s1', settings('a'))
    const first = actions()
    const second = actions()

    const adding = first.addCurrent()
    expect(first.canAdd.value).toBe(false)
    await second.addCurrent()
    answer.resolve(problem(409, 'queue.refused', 'Refused'))
    await adding

    expect(queueBodies()).toHaveLength(1)
    // The API client's own toast of the problem; no second one.
    expect(toasts()).toEqual([{ severity: 'error', summary: 'Refused', detail: undefined }])
    expect(first.canAdd.value).toBe(true)
  })
})

describe('addAll', () => {
  it("drafts the other sources with the editor's preset, takes the open job as edited, and adds those without errors in order", async () => {
    const edited = settings('b', '/out/b-edited.mkv')
    editor.presetId = 'preset-1'
    sources.entries = [entry('a'), entry('b'), entry('c'), entry('d')]
    open('b', edited)
    server.on('POST /api/jobs/draft', (request) => {
      const { source_id } = request.body as { source_id: string }
      if (source_id === 'c') {
        return { job: settings('c'), naming: {}, issues: [issue('error', 'No English audio')] }
      }
      if (source_id === 'd') return problem(404, 'sources.unknown', 'Unknown source')
      return { job: settings(source_id), naming: {}, issues: [issue('warning', 'fine')] }
    })

    await actions().addAll()

    const drafts = server.requests
      .filter((request) => request.path === '/api/jobs/draft')
      .map((request) => request.body)
    expect(drafts).toEqual([
      { source_id: 'a', preset_id: 'preset-1' },
      { source_id: 'c', preset_id: 'preset-1' },
      { source_id: 'd', preset_id: 'preset-1' },
    ])
    expect(queueBodies()).toEqual([[settings('a'), edited]])
    expect(toasts()).toEqual([
      { severity: 'success', summary: '2 jobs added to the queue', detail: undefined },
      {
        severity: 'warn',
        summary: '2 sources were not added',
        detail: 'c.mkv: No English audio\nd.mkv: Unknown source',
      },
    ])
  })

  it('lists the open job when it has an error, and adds nothing when no job is ready', async () => {
    sources.entries = [entry('a')]
    open('a', settings('a'))
    validation.issues = [issue('error', 'The encoder is not available')]
    await actions().addAll()

    expect(queueBodies()).toEqual([])
    expect(toasts().map((toast) => toast.detail)).toEqual(['a.mkv: The encoder is not available'])
  })

  it('takes the open job once the value of the focused field and its check are in', async () => {
    sources.entries = [entry('a')]
    open('a', settings('a'))
    const field = document.createElement('input')
    document.body.append(field)
    field.addEventListener('blur', () => {
      open('a', settings('a', '/out/typed.mkv'))
      validation.pending = true
    })
    field.focus()

    const adding = actions().addAll()
    await settle()
    expect(queueBodies()).toEqual([])
    validation.pending = false
    await adding
    expect(queueBodies()).toEqual([[settings('a', '/out/typed.mkv')]])
  })

  it('lists a draft without an output path and a job the queue took as failed', async () => {
    sources.entries = [entry('a'), entry('b')]
    server
      .on('POST /api/jobs/draft', (request) => {
        const { source_id } = request.body as { source_id: string }
        return { job: settings(source_id, source_id === 'a' ? null : undefined), naming: {} }
      })
      .on('POST /api/queue', (request) =>
        (request.body as { jobs: JobSettings[] }).jobs.map((job) =>
          queued(job, { state: 'failed', error: 'Output claimed' }),
        ),
      )
    await actions().addAll()

    expect(queueBodies()).toEqual([[settings('b')]])
    expect(toasts()).toEqual([
      {
        severity: 'warn',
        summary: '2 sources were not added',
        detail: 'a.mkv: it has no output path\nb.mkv: Output claimed',
      },
    ])
  })

  it('is possible with open sources only, and again after the queue refused the jobs', async () => {
    const { canAddAll, addAll } = actions()
    expect(canAddAll.value).toBe(false)
    sources.entries = [entry('a'), entry('b')]
    expect(canAddAll.value).toBe(true)
    server
      .on('POST /api/jobs/draft', (request) =>
        (request.body as { source_id: string }).source_id === 'a'
          ? { job: settings('a'), naming: {} }
          : problem(404, 'sources.unknown', 'Unknown source'),
      )
      .on('POST /api/queue', () => problem(409, 'queue.refused', 'Refused'))
    await addAll()

    // Only the API client's toast of the problem: a list of "the others" would claim that the
    // rest was added.
    expect(toasts()).toEqual([{ severity: 'error', summary: 'Refused', detail: undefined }])
    expect(canAddAll.value).toBe(true)
  })

  it('adds the open job as it was when Add all was clicked', async () => {
    const job = settings('b')
    sources.entries = [entry('a'), entry('b')]
    open('b', job)
    const draft = deferred<unknown>()
    server.on('POST /api/jobs/draft', () => draft.promise)

    const adding = actions().addAll()
    await settle()
    // An edit while the other source is still being drafted.
    ;(editor.target as { job: JobSettings }).job.output = {
      ...settings('b').output,
      path: '/out/changed.mkv',
    } as JobSettings['output']
    draft.resolve({ job: settings('a'), naming: {} })
    await adding

    expect(queueBodies()[0]?.[1]?.output?.path).toBe('/out/b.mkv')
  })
})

describe('start and canStart', () => {
  it('starts the queue', async () => {
    server.on('POST /api/queue/start', {})
    await actions().start()
    await settle()
    expect(server.count('POST /api/queue/start')).toBe(1)
  })

  it('is possible only when a Start would hand waiting jobs to the runner', async () => {
    const queue = useQueueStore()
    const { canStart } = actions()
    expect(canStart.value).toBe(false)

    server.on('GET /api/queue', { jobs: [queued(settings('a'))], processing: false, only: null })
    await queue.resync()
    expect(canStart.value).toBe(true)

    queue.onQueueProcessing({
      type: 'queue.processing',
      processing: true,
      only: null,
      reason: 'start',
    })
    expect(canStart.value).toBe(false)

    queue.onQueueProcessing({
      type: 'queue.processing',
      processing: true,
      only: ['x'],
      reason: 'start',
    })
    expect(canStart.value).toBe(true)
  })
})
