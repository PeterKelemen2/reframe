import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PrimeVue from 'primevue/config'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, reactive } from 'vue'

import { ApiError, configureClient } from '@/api/client'
import { deferred, FakeServer } from '@/api/testing/fakes'
import type { BatchResolution, JobSettings, QueueJob, SourceEntry } from '@/api/types'
import QueueGroupDialog from '@/components/matrix/QueueGroupDialog.vue'
import {
  animeResolution,
  animeSources,
  fixedE11,
  sourceIdOf,
  withRow,
} from '@/components/matrix/testing'
import { createAppI18n } from '@/i18n'
import type { EditorTarget } from '@/stores/editor'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

import { type QueueGroup, useQueueGroup } from './useQueueGroup'

// Test doubles of the editor and sources stores: the members their contracts give.
const editor = reactive({
  target: null as EditorTarget | null,
  editGroup: vi.fn<(groupId: string) => Promise<void>>(async () => {}),
  resolveNow: vi.fn<() => Promise<BatchResolution>>(),
})
const sources = reactive({ entries: [] as SourceEntry[] })
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
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

  it('queues nothing when the resolve fails (the API toast says why) and can run again', async () => {
    editor.resolveNow.mockRejectedValueOnce(
      new ApiError(500, { title: 'No', status: 500 } as never),
    )
    const group = setup()
    await group.queueGroup('g1')
    expect(queueBodies()).toEqual([])
    expect(group.busy.value).toBe(false)
    await group.queueGroup('g1')
    expect(queueBodies()).toHaveLength(1)
  })

  it('lists the jobs the queue refused', async () => {
    server.on('POST /api/queue', (request) =>
      (request.body as { jobs: JobSettings[] }).jobs.map((job, index) =>
        queued(job, index === 2 ? { state: 'failed', error: 'Disk full' } : {}),
      ),
    )
    await setup().queueGroup('g1')
    expect(toasts()).toEqual([
      { severity: 'success', summary: 'Queued 11 jobs', detail: undefined },
      {
        severity: 'warn',
        summary: '1 job was not queued',
        detail: 'Anime.Show.S01E03.Storm.BluRay.x264-GRP.mkv: Disk full',
      },
    ])
  })
})

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
