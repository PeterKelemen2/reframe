import { flushPromises } from '@vue/test-utils'
import DataTable from 'primevue/datatable'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import { ApiError } from '@/api/client'
import type { JobSettings } from '@/api/types'
import { SourceOpenError } from '@/stores/sources'

import QueueTable from './QueueTable.vue'
import { job, mountQueue, queueDouble, resetQueue } from './testing'

const queue = queueDouble()
const editor = reactive({
  loadJob: vi.fn<(settings: JobSettings) => Promise<void>>(async () => {}),
})
const platform = vi.hoisted(() => ({
  kind: 'web' as 'web' | 'desktop',
  revealInFolder: vi.fn<(path: string) => Promise<void> | null>(() => null),
}))
vi.mock('@/stores/queue', () => ({ useQueueStore: () => queue }))
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))
vi.mock('@/platform', () => ({ platform }))

const mounted: { unmount(): void }[] = []

beforeEach(() => {
  resetQueue(queue)
  vi.clearAllMocks()
  platform.kind = 'web'
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountTable() {
  const result = await mountQueue(QueueTable)
  mounted.push(result.wrapper)
  return result
}

function row(id: string): HTMLElement {
  const cell = document.querySelector(`[data-job="${id}"]`)
  const tr = cell?.closest('tr')
  if (!tr) throw new Error(`no row ${id}`)
  return tr
}

function button(id: string, selector: string): HTMLButtonElement {
  const found = row(id).querySelector<HTMLButtonElement>(selector)
  if (!found) throw new Error(`no ${selector} in row ${id}`)
  return found
}

const actions = (id: string) =>
  [...row(id).querySelectorAll('[data-action]')].map((el) => el.getAttribute('data-action'))

const order = () =>
  [...document.querySelectorAll('[data-job]')].map((el) => el.getAttribute('data-job'))

describe('the queue table', () => {
  it('shows the jobs in queue order with state, source, output, preset and live progress', async () => {
    queue.jobs = [
      job('a', 'running', {
        progress: {
          percent: 42.5,
          fps: 24,
          speed: 1.5,
          eta: 90,
          output_size: 2048,
          step: 1,
          step_count: 2,
          step_kind: 'pass2',
        },
      }),
      job('b', 'waiting', { output_path: '/out/b (1).mkv' }),
    ]
    await mountTable()
    expect(order()).toEqual(['a', 'b'])
    const cells = [...row('a').querySelectorAll('td')].map((td) => td.textContent?.trim())
    expect(cells.slice(1, 10)).toEqual([
      'Running',
      'a.mkv',
      'a.mkv',
      'H.265 MKV 1080p',
      '42.5 %Pass 2 of 2 · step 2 of 2',
      '24.0 fps',
      '1.50×',
      '1:30',
      '2 KiB',
    ])
    // The output's final name once the run chose it.
    expect(row('b').querySelector('[data-field="output"]')?.textContent?.trim()).toBe('b (1).mkv')
  })

  it('follows a job that the store replaces with new progress', async () => {
    queue.jobs = [job('a', 'running', { progress: { percent: 10, step: 0, step_count: 1 } })]
    await mountTable()
    queue.jobs = [job('a', 'running', { progress: { percent: 55, step: 0, step_count: 1 } })]
    await flushPromises()
    expect(row('a').querySelector('[data-field="percent"]')?.textContent?.trim()).toBe('55.0 %')
  })

  it.each([
    ['running', 'pause', 'pause'],
    ['paused', 'resume', 'resume'],
    ['running', 'cancel', 'cancel'],
    ['failed', 'retry', 'retry'],
    ['done', 'duplicate', 'duplicate'],
    ['cancelled', 'remove', 'remove'],
  ] as const)('a %s job’s %s button calls %s with its id', async (state, action, method) => {
    queue.jobs = [job('x'), job('a', state)]
    await mountTable()
    button('a', `[data-action="${action}"]`).click()
    await flushPromises()
    expect(queue[method]).toHaveBeenCalledWith('a')
  })

  it('offers only the actions that fit the state', async () => {
    queue.jobs = [job('a', 'running'), job('b', 'done')]
    await mountTable()
    expect(actions('a')).toEqual(['pause', 'cancel', 'log', 'edit', 'duplicate'])
    expect(actions('b')).toEqual(['log', 'edit', 'duplicate', 'remove'])
  })

  it('reveals a done job’s output in its folder on the desktop only', async () => {
    queue.jobs = [job('a', 'done', { output_path: '/out/a (1).mkv' })]
    await mountTable()
    expect(row('a').querySelector('[data-action="reveal"]')).toBeNull()
    mounted.splice(0).forEach((wrapper) => wrapper.unmount())
    platform.kind = 'desktop'
    await mountTable()
    button('a', '[data-action="reveal"]').click()
    expect(platform.revealInFolder).toHaveBeenCalledWith('/out/a (1).mkv')
  })

  it('moves a job up by keyboard: the two jobs swap, the focus stays on the moved job', async () => {
    queue.jobs = [job('a'), job('b'), job('c')]
    await mountTable()
    button('c', '[data-move="up"]').click()
    await flushPromises()
    expect(queue.reorder).toHaveBeenCalledWith(['c', 'b'])
    // The double does not reorder, so the moved job's buttons are still in its row.
    expect(document.activeElement).toBe(button('c', '[data-move="up"]'))
  })

  it('moves a job down by keyboard', async () => {
    queue.jobs = [job('a'), job('b'), job('c')]
    await mountTable()
    button('a', '[data-move="down"]').click()
    await flushPromises()
    expect(queue.reorder).toHaveBeenCalledWith(['b', 'a'])
    expect(button('a', '[data-move="up"]').disabled).toBe(true)
    expect(button('c', '[data-move="down"]').disabled).toBe(true)
  })

  it('sends the dragged order of every job', async () => {
    queue.jobs = [job('a'), job('b'), job('c')]
    const { wrapper } = await mountTable()
    const table = wrapper.findComponent(DataTable)
    const rows = table.props('value') as { job: { id: string } }[]
    table.vm.$emit('row-reorder', {
      dragIndex: 2,
      dropIndex: 0,
      value: [rows[2], rows[0], rows[1]],
    })
    await flushPromises()
    expect(queue.reorder).toHaveBeenCalledWith(['c', 'a', 'b'])
  })

  it('loads a job back into the editor and goes to the workspace', async () => {
    queue.jobs = [job('a', 'done')]
    const { router } = await mountTable()
    button('a', '[data-action="edit"]').click()
    await flushPromises()
    expect(editor.loadJob).toHaveBeenCalledWith(queue.jobs[0]?.settings)
    expect(router.currentRoute.value.name).toBe('workspace')
  })

  it('stays on the queue when the source cannot be opened (the reason is a toast)', async () => {
    queue.jobs = [job('a', 'done')]
    editor.loadJob.mockRejectedValueOnce(new SourceOpenError('gone'))
    const { router } = await mountTable()
    button('a', '[data-action="edit"]').click()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('queue')
  })

  it('keeps going when the server refuses an action (the API client showed it)', async () => {
    queue.jobs = [job('a', 'running')]
    queue.pause.mockRejectedValueOnce(new ApiError(409, { title: 'No', status: 409 } as never))
    await mountTable()
    button('a', '[data-action="pause"]').click()
    await flushPromises()
    button('a', '[data-action="pause"]').click()
    await flushPromises()
    expect(queue.pause).toHaveBeenCalledTimes(2)
  })

  it('asks the view to open the log of a job, from its button', async () => {
    queue.jobs = [job('a', 'running')]
    const { wrapper } = await mountTable()
    button('a', '[data-action="log"]').click()
    expect(wrapper.emitted('openLog')?.[0]).toEqual(['a', button('a', '[data-action="log"]')])
  })

  it('shows the error and the issues of a failed job under its row', async () => {
    queue.jobs = [
      job('a', 'failed', {
        error: 'The encoder is not available',
        issues: [
          {
            severity: 'error',
            code: 'encoder.unavailable',
            path: 'video.encoder',
            message: 'No NVENC',
          },
          { severity: 'warning', code: 'x', path: 'audio[0]', message: 'Loud' },
        ],
      }),
      job('b', 'done'),
    ]
    await mountTable()
    const problems = [...document.querySelectorAll('[data-field="problem"]')]
    expect(problems).toHaveLength(1)
    expect(problems[0]?.querySelector('[data-field="error"]')?.textContent?.trim()).toBe(
      'The encoder is not available',
    )
    expect(
      [...(problems[0]?.querySelectorAll('li') ?? [])].map((li) =>
        li.getAttribute('data-severity'),
      ),
    ).toEqual(['error', 'warning'])
  })

  it('says that the queue is empty and links to the workspace', async () => {
    await mountTable()
    const empty = document.querySelector('[data-state="empty"]')
    expect(empty?.textContent).toContain('The queue is empty')
    expect(empty?.querySelector('a')?.getAttribute('href')).toBe('/')
  })
})
