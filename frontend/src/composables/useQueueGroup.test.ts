import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, reactive } from 'vue'

import { ApiError, configureClient } from '@/api/client'
import { deferred, FakeServer } from '@/api/testing/fakes'
import type {
  BatchGroup,
  BatchResolution,
  JobSettings,
  QueueJob,
  Resolution,
  SourceEntry,
} from '@/api/types'
import QueueGroupDialog from '@/components/matrix/QueueGroupDialog.vue'
import {
  animeResolution,
  animeSources,
  fixedE11,
  sourceIdOf,
  withRow,
} from '@/components/matrix/testing'
import { createAppI18n } from '@/i18n'
import type { EditorTarget, MatrixOptions } from '@/stores/editor'
import { useTasksStore } from '@/stores/tasks'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

import { type QueueGroup, useQueueGroup } from './useQueueGroup'

const DETECTION_CANCELLED = 'batch.detection_cancelled'

// Test doubles of the editor and sources stores: the members their contracts give.
const editor = reactive({
  target: null as EditorTarget | null,
  group: null as BatchGroup | null,
  editGroup: vi.fn<(groupId: string) => Promise<void>>(async () => {}),
  resolveNow: vi.fn<(options?: MatrixOptions) => Promise<BatchResolution>>(),
})
const sources = reactive({ entries: [] as SourceEntry[] })
vi.mock('@/stores/editor', () => ({
  useEditorStore: () => editor,
  DETECTION_CANCELLED: 'batch.detection_cancelled',
}))
vi.mock('@/stores/sources', () => ({ useSourcesStore: () => sources }))

function editing(groupId: string): EditorTarget {
  return {
    kind: 'group',
    groupId,
    sourceId: sourceIdOf(1),
    job: {} as never,
    template: {} as never,
    presetId: null,
    overrides: {},
    scope: 'group',
  }
}

let server: FakeServer
const mounted: { unmount(): void }[] = []

function queued(job: JobSettings, extra: Partial<QueueJob> = {}): QueueJob {
  return {
    id: `job-${job.source.path}`,
    position: 0,
    state: 'waiting',
    settings: job,
    created_at: '2026-11-01T10:00:00Z',
    ...extra,
  } as QueueJob
}

/** The composable, and the dialog that answers its question. */
function setup(): QueueGroup {
  let result: QueueGroup | undefined
  const Host = defineComponent({
    setup() {
      result = useQueueGroup()
      return () => h(QueueGroupDialog)
    },
  })
  mounted.push(
    mount(Host, {
      attachTo: document.body,
      global: { plugins: [createAppI18n(), [PrimeVue, { theme: 'none' }]] },
    }),
  )
  return result as QueueGroup
}

function queueBodies(): JobSettings[][] {
  return server.requests
    .filter((request) => request.method === 'POST' && request.path === '/api/queue')
    .map((request) => (request.body as { jobs: JobSettings[] }).jobs)
}

function outputs(jobs: JobSettings[] | undefined): string[] {
  return (jobs ?? []).map((job) => (job.output?.path ?? '').replace('/output/', ''))
}

function toasts() {
  return useToastStore().items.map(({ severity, summary, detail }) => ({
    severity,
    summary,
    detail,
  }))
}

function button(role: string): HTMLButtonElement {
  const found = document.querySelector<HTMLButtonElement>(`[data-role="${role}"]`)
  if (!found) throw new Error(`no ${role}`)
  return found
}

beforeEach(() => {
  setActivePinia(createPinia())
  editor.target = editing('g1')
  editor.group = animeResolution().group ?? null
  editor.editGroup.mockClear()
  editor.resolveNow.mockReset()
  editor.resolveNow.mockImplementation(async () => withRow(animeResolution(), fixedE11()))
  sources.entries = animeSources()
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
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

describe('queueGroup without errors', () => {
  it('queues one job per file in episode order with their names, once, and says so', async () => {
    const group = setup()
    await group.queueGroup('g1')
    expect(editor.editGroup).not.toHaveBeenCalled()
    expect(editor.resolveNow).toHaveBeenCalledOnce()
    expect(editor.resolveNow).toHaveBeenCalledWith({
      detectCrop: true,
      onTask: expect.any(Function),
    })
    const bodies = queueBodies()
    expect(bodies).toHaveLength(1)
    expect(outputs(bodies[0])).toEqual([
      'Anime.Show.S01E01.Pilot.mkv',
      'Anime.Show.S01E02.Departure.mkv',
      'Anime.Show.S01E03.Storm.mkv',
      'Anime.Show.S01E04.Signal.mkv',
      'Anime.Show.S01E05.Echoes.mkv',
      'Anime.Show.S01E06.Harbor.mkv',
      'Anime.Show.S01E07.Embers.mkv',
      'Anime.Show.S01E08.Drift.mkv',
      'Anime.Show.S01E09.Lantern.mkv',
      'Anime.Show.S01E10.Tides.mkv',
      'Anime.Show.S01E11.Static.mkv',
      'Anime.Show.S01E12.Homecoming.mkv',
    ])
    expect(toasts()).toEqual([
      { severity: 'success', summary: 'Queued 12 jobs', detail: undefined },
    ])
    expect(group.busy.value).toBe(false)
  })

  it('edits the group first when another target is edited', async () => {
    editor.target = editing('other')
    editor.editGroup.mockImplementation(async (groupId) => {
      expect(editor.resolveNow).not.toHaveBeenCalled()
      editor.target = editing(groupId)
    })
    await setup().queueGroup('g1')
    expect(editor.editGroup).toHaveBeenCalledExactlyOnceWith('g1')
    expect(queueBodies()).toHaveLength(1)
  })

  it('works when called outside a component, and shares the wait with every caller', async () => {
    const answer = deferred<BatchResolution>()
    editor.resolveNow.mockImplementation(() => answer.promise)
    const fromHandler = useQueueGroup()
    const first = fromHandler.queueGroup('g1')
    await useQueueGroup().queueGroup('g1')
    expect(useQueueGroup().busy.value).toBe(true)
    answer.resolve(withRow(animeResolution(), fixedE11()))
    await first
    expect(editor.resolveNow).toHaveBeenCalledOnce()
    expect(queueBodies()).toHaveLength(1)
    expect(toasts()).toEqual([
      { severity: 'success', summary: 'Queued 12 jobs', detail: undefined },
    ])
  })

  it('does nothing on a second call while the first runs', async () => {
    const answer = deferred<BatchResolution>()
    editor.resolveNow.mockImplementation(() => answer.promise)
    const group = setup()
    const first = group.queueGroup('g1')
    expect(group.busy.value).toBe(true)
    await group.queueGroup('g1')
    answer.resolve(withRow(animeResolution(), fixedE11()))
    await first
    expect(editor.resolveNow).toHaveBeenCalledOnce()
    expect(queueBodies()).toHaveLength(1)
  })

  it('queues nothing when the resolve fails, says why, and can run again', async () => {
    editor.resolveNow.mockRejectedValueOnce(
      new ApiError(500, { title: 'No', detail: 'Broken', status: 500, code: 'x' } as never),
    )
    const group = setup()
    await group.queueGroup('g1')
    expect(queueBodies()).toEqual([])
    expect(toasts()).toEqual([{ severity: 'error', summary: 'No', detail: 'Broken' }])
    expect(group.busy.value).toBe(false)
    await group.queueGroup('g1')
    expect(queueBodies()).toHaveLength(1)
  })

  it('adds no toast when an edit did not reach the group: the edit showed its own', async () => {
    editor.resolveNow.mockRejectedValueOnce(
      new ApiError(0, {
        title: 'An edit did not reach the group',
        status: 0,
        code: 'edit.failed',
      } as never),
    )
    await setup().queueGroup('g1')
    expect(queueBodies()).toEqual([])
    expect(toasts()).toEqual([])
  })

  it('names the files that changed on disk when the resolve finds a changed file', async () => {
    const listed = animeSources()
    ;(listed[1] as SourceEntry).source = null
    // Another open file, not of the group, changed too.
    listed.push({ id: 'other', path: '/media/Other.mkv', source: null } as SourceEntry)
    server.on('GET /api/sources', listed)
    editor.resolveNow.mockRejectedValueOnce(
      new ApiError(409, {
        title: 'The file changed or is gone since it was probed',
        detail: 'Probe it again with POST /api/sources.',
        status: 409,
        code: 'source.stale',
      } as never),
    )
    await setup().queueGroup('g1')
    expect(queueBodies()).toEqual([])
    expect(toasts()).toEqual([
      {
        severity: 'error',
        summary: '1 file of the group changed since it was opened',
        detail:
          'Remove it from the sources and open it again:\nAnime.Show.S01E02.Departure.BluRay.x264-GRP.mkv',
      },
    ])
  })

  it('says what the queue did when it added some jobs as failed', async () => {
    server.on('POST /api/queue', (request) =>
      (request.body as { jobs: JobSettings[] }).jobs.map((job, index) =>
        queued(
          job,
          index < 2 ? { state: 'failed', error: 'Its output is already planned in the queue' } : {},
        ),
      ),
    )
    await setup().queueGroup('g1')
    expect(toasts()).toEqual([
      {
        severity: 'warn',
        summary: '12 jobs added to the queue; 2 of them failed',
        detail: [
          'Anime.Show.S01E01.Pilot.BluRay.x264-GRP.mkv: Its output is already planned in the queue',
          'Anime.Show.S01E02.Departure.BluRay.x264-GRP.mkv: Its output is already planned in the queue',
        ].join('\n'),
      },
    ])
  })

  it('keeps the toast short when the queue adds every job as failed', async () => {
    server.on('POST /api/queue', (request) =>
      (request.body as { jobs: JobSettings[] }).jobs.map((job) =>
        queued(job, { state: 'failed', error: 'Planned already' }),
      ),
    )
    await setup().queueGroup('g1')
    const [toast] = toasts()
    expect(toast?.summary).toBe('12 jobs added to the queue; 12 of them failed')
    expect(toast?.detail?.split('\n')).toEqual([
      'Anime.Show.S01E01.Pilot.BluRay.x264-GRP.mkv: Planned already',
      'Anime.Show.S01E02.Departure.BluRay.x264-GRP.mkv: Planned already',
      'Anime.Show.S01E03.Storm.BluRay.x264-GRP.mkv: Planned already',
      '… and 9 more failed jobs: the queue lists them.',
    ])
  })

  it('says how many files are queued without part of their stale override', async () => {
    editor.resolveNow.mockImplementation(async () =>
      withRow(withRow(animeResolution(), fixedE11()), staleRow(3)),
    )
    await setup().queueGroup('g1')
    expect(queueBodies()[0]).toHaveLength(12)
    expect(toasts()).toEqual([
      {
        severity: 'warn',
        summary: 'Queued 12 jobs',
        detail: expect.stringMatching(/^1 file is queued without part of its per-file changes/),
      },
    ])
  })
})

/** A detection that started task `t-crop` and waits for the test to end it. */
function detecting() {
  const answer = deferred<BatchResolution>()
  editor.resolveNow.mockImplementation((options) => {
    options?.onTask?.('t-crop')
    return answer.promise
  })
  return answer
}

function measuring(message: string, progress: number): void {
  useTasksStore().onTaskProgress({
    type: 'task.progress',
    task: { id: 't-crop', kind: 'batch_cropdetect', state: 'running', progress, message },
  })
}

describe('the crop detection before queueing', () => {
  it('says which file it measures while it runs, then queues', async () => {
    const answer = detecting()
    const group = setup()
    expect(group.detection.value).toBeNull()
    const running = group.queueGroup('g1')
    await flushPromises()
    expect(group.detection.value).toEqual({ message: 'Detecting the crop…' })
    measuring('Detecting the crop: file 3 of 12', 100 * (2 / 12))
    expect(group.detection.value).toEqual({ message: 'Detecting the crop: file 3 of 12' })
    expect(queueBodies()).toEqual([])
    answer.resolve(withRow(animeResolution(), fixedE11()))
    await running
    expect(group.detection.value).toBeNull()
    expect(queueBodies()).toHaveLength(1)
  })

  it('Cancel cancels the task, and a cancelled detection queues nothing and says nothing', async () => {
    server.on('POST /api/tasks/t-crop/cancel', { cancelled: true })
    const answer = detecting()
    const group = setup()
    const running = group.queueGroup('g1')
    await flushPromises()
    measuring('Detecting the crop: file 1 of 12', 0)
    await group.cancelDetection()
    expect(
      server.requests.filter((request) => request.path === '/api/tasks/t-crop/cancel'),
    ).toHaveLength(1)
    answer.reject(
      new ApiError(0, { title: 'Cancelled', status: 0, code: DETECTION_CANCELLED } as never),
    )
    await running
    expect(queueBodies()).toEqual([])
    expect(toasts()).toEqual([])
    expect(group.detection.value).toBeNull()
    expect(group.busy.value).toBe(false)
  })

  it('a failed detection queues nothing and says why', async () => {
    const answer = detecting()
    const group = setup()
    const running = group.queueGroup('g1')
    await flushPromises()
    answer.reject(
      new ApiError(0, {
        title: 'The crop of the group’s files could not be detected',
        detail: 'ffmpeg stopped',
        status: 0,
        code: 'batch.detection_failed',
      } as never),
    )
    await running
    expect(queueBodies()).toEqual([])
    expect(toasts()).toEqual([
      {
        severity: 'error',
        summary: 'The crop of the group’s files could not be detected',
        detail: 'ffmpeg stopped',
      },
    ])
    expect(group.detection.value).toBeNull()
  })
})

/** Episode `episode`'s row with a stale override's warning. */
function staleRow(episode: number): Resolution {
  const row = animeResolution().rows?.[episode - 1] as Resolution
  row.status = 'warning'
  row.issues = [
    ...(row.issues ?? []),
    {
      severity: 'warning',
      code: 'batch.override_stale',
      path: 'override.job.audio.0',
      message: 'The override was made for another template.',
    },
  ]
  return row
}

async function asked(group: QueueGroup): Promise<{ running: Promise<void> }> {
  editor.resolveNow.mockImplementation(async () => animeResolution())
  const running = group.queueGroup('g1')
  await flushPromises()
  return { running }
}

describe('queueGroup with errors', () => {
  it('lists each file with errors and its first error, and queues nothing yet', async () => {
    const group = setup()
    const { running } = await asked(group)
    expect(group.question.value?.failed).toEqual([
      {
        sourceId: sourceIdOf(11),
        label: 'E11',
        message: 'No source track matches rule A2 eng DTS-HD MA→AAC 2.0, and the rule is required.',
      },
    ])
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain('E11')
    expect(queueBodies()).toEqual([])
    button('cancel').click()
    await running
  })

  it('queues the valid files in episode order, skipping the others', async () => {
    const group = setup()
    const { running } = await asked(group)
    button('valid').click()
    await running
    const bodies = queueBodies()
    expect(bodies).toHaveLength(1)
    expect(outputs(bodies[0])).toHaveLength(11)
    expect(outputs(bodies[0])).not.toContain('Anime.Show.S01E11.Static.mkv')
    expect(outputs(bodies[0])[10]).toBe('Anime.Show.S01E12.Homecoming.mkv')
    expect(group.question.value).toBeNull()
  })

  it('opens the matrix at the first file with errors and queues nothing', async () => {
    const group = setup()
    const { running } = await asked(group)
    button('matrix').click()
    await running
    expect(useUiStore().matrixOpen).toBe(true)
    expect(useUiStore().matrixFocus).toBe(sourceIdOf(11))
    expect(queueBodies()).toEqual([])
  })

  it('gives the first focus to Open matrix, not to queueing', async () => {
    const group = setup()
    const { running } = await asked(group)
    await vi.waitFor(() => expect(document.activeElement).toBe(button('matrix')))
    button('cancel').click()
    await running
  })

  it('gives the focus back to what started it after Cancel and after queueing', async () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    const group = setup()
    // The button that started it is disabled while busy: the page has the focus meanwhile.
    editor.resolveNow.mockImplementation(async () => {
      opener.blur()
      return animeResolution()
    })
    async function answered(choice: string): Promise<void> {
      opener.focus()
      const running = group.queueGroup('g1')
      await vi.waitFor(() => expect(document.activeElement).toBe(button('matrix')))
      button(choice).click()
      await running
      expect(document.activeElement).toBe(opener)
    }
    await answered('cancel')
    await answered('valid')
  })

  it('says how many valid files lose part of their stale override', async () => {
    const group = setup()
    editor.resolveNow.mockImplementation(async () => withRow(animeResolution(), staleRow(3)))
    const running = group.queueGroup('g1')
    await flushPromises()
    expect(group.question.value?.stale).toBe(1)
    expect(document.querySelector('[data-role="stale"]')?.textContent).toContain(
      '1 of the valid files loses part of its per-file changes',
    )
    button('cancel').click()
    await running
  })

  it('queues nothing on Cancel, and a second call while asking does nothing', async () => {
    const group = setup()
    const { running } = await asked(group)
    await group.queueGroup('g1')
    button('cancel').click()
    await running
    expect(editor.resolveNow).toHaveBeenCalledOnce()
    expect(queueBodies()).toEqual([])
    expect(group.busy.value).toBe(false)
  })
})
