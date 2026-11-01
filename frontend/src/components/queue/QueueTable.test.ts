import { flushPromises } from '@vue/test-utils'
import DataTable from 'primevue/datatable'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import { ApiError } from '@/api/client'
import { deferred } from '@/api/testing/fakes'
import type { JobSettings } from '@/api/types'
import { SourceOpenError } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

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

function nvencSettings(id: string, video: object): JobSettings {
  return { ...job(id).settings, preset_name: 'H.265 NVENC 1080p', video } as JobSettings
}

function presetCell(id: string): (string | undefined)[] {
  return ['preset', 'encoder'].map((field) =>
    row(id).querySelector(`[data-field="${field}"]`)?.textContent?.trim(),
  )
}

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

  it('shows the encoder a job uses under its preset: an edited job’s own, or a copied video', async () => {
    queue.jobs = [
      job('a', 'waiting', {
        settings: nvencSettings('a', { encoder: 'libx264', passthrough: false }),
      }),
      job('b', 'waiting', {
        settings: nvencSettings('b', { encoder: 'hevc_nvenc', passthrough: true }),
      }),
    ]
    await mountTable()
    useSystemStore().definitions = {
      video_encoders: { libx264: { label: 'x264' }, hevc_nvenc: { label: 'NVIDIA NVENC H.265' } },
    } as never
    await flushPromises()
    expect(presetCell('a')).toEqual(['H.265 NVENC 1080p', 'x264'])
    expect(presetCell('b')).toEqual(['H.265 NVENC 1080p', 'Video copied'])
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

  it('puts the focus into the workspace after Edit, and keeps it on Edit while it loads', async () => {
    queue.jobs = [job('a', 'done')]
    const loading = deferred()
    editor.loadJob.mockImplementationOnce(() => loading.promise)
    // The selected tab of the workspace, which the router shows in the app.
    const tab = document.createElement('button')
    tab.setAttribute('role', 'tab')
    tab.setAttribute('aria-selected', 'true')
    const tabs = document.createElement('div')
    tabs.className = 'editor-tabs'
    tabs.append(tab)
    await mountTable()
    document.body.append(tabs)
    const edit = button('a', '[data-action="edit"]')
    edit.focus()
    edit.click()
    await flushPromises()
    expect(document.activeElement).toBe(edit)
    expect(edit.disabled).toBe(false)
    expect(edit.getAttribute('aria-busy')).toBe('true')
    loading.resolve()
    await flushPromises()
    expect(document.activeElement).toBe(tab)
  })

  it.each([
    ['running', 'pause', 'paused', 'resume'],
    ['paused', 'resume', 'running', 'pause'],
    ['failed', 'retry', 'waiting', 'cancel'],
    ['waiting', 'cancel', 'cancelled', 'retry'],
    ['running', 'cancel', 'cancelled', 'retry'],
  ] as const)(
    'after a %s job’s %s, the focus goes to the action that took its place',
    async (state, action, next, replacement) => {
      queue.jobs = [job('x', 'done'), job('a', state)]
      await mountTable()
      queue[action].mockImplementationOnce(async () => {
        queue.jobs = [job('x', 'done'), job('a', next)]
      })
      const pressed = button('a', `[data-action="${action}"]`)
      pressed.focus()
      pressed.click()
      await flushPromises()
      expect(pressed.isConnected).toBe(false)
      expect(document.activeElement).toBe(button('a', `[data-action="${replacement}"]`))
    },
  )

  it('after a removal, the focus goes to the same button of the next job, else of the last one', async () => {
    queue.jobs = [job('a', 'done'), job('b', 'done'), job('c', 'failed')]
    queue.remove.mockImplementation(async (id) => {
      queue.jobs = queue.jobs.filter((found) => found.id !== id)
    })
    await mountTable()
    button('a', '[data-action="remove"]').focus()
    button('a', '[data-action="remove"]').click()
    await flushPromises()
    expect(document.activeElement).toBe(button('b', '[data-action="remove"]'))
    button('c', '[data-action="log"]').focus()
    button('c', '[data-action="log"]').click()
    queue.jobs = [job('b', 'done')]
    await flushPromises()
    expect(document.activeElement).toBe(button('b', '[data-action="log"]'))
    button('b', '[data-action="remove"]').focus()
    button('b', '[data-action="remove"]').click()
    await flushPromises()
    expect(document.activeElement?.textContent?.trim()).toBe('Go to the workspace')
  })

  it('leaves the focus alone when the jobs change and the focused button stays', async () => {
    queue.jobs = [job('a', 'running', { progress: { percent: 10, step: 0, step_count: 1 } })]
    await mountTable()
    const pause = button('a', '[data-action="pause"]')
    pause.focus()
    queue.jobs = [job('a', 'running', { progress: { percent: 20, step: 0, step_count: 1 } })]
    await flushPromises()
    expect(document.activeElement).toBe(pause)
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

  it('shows an in-place job’s target as its source edited in place, not as an output file', async () => {
    const inPlace = job('a', 'done', { output_path: '/media/a.mkv' })
    inPlace.settings = {
      ...inPlace.settings,
      output: { path: '/media/a.mkv', edit_in_place: true },
    } as JobSettings
    queue.jobs = [inPlace, job('b', 'waiting')]
    await mountTable()
    const target = row('a').querySelector<HTMLElement>('[data-field="output"]')!
    expect(target.textContent?.trim()).toBe('Source, edited in place')
    target.dispatchEvent(new MouseEvent('mouseenter'))
    await vi.waitFor(() =>
      expect(document.querySelector('.p-tooltip')?.textContent).toBe(
        'mkvpropedit changes /media/a.mkv itself: no new file is written.',
      ),
    )
    expect(row('b').querySelector('[data-field="output"]')?.textContent?.trim()).toBe('b.mkv')
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

  it('says why a job failed once: an issue that its error quotes is not listed again', async () => {
    const claimed =
      'a.mkv is also the output of a job that is waiting in the queue (a.mkv): this job would replace that file.'
    queue.jobs = [
      job('a', 'failed', {
        error: `The job has errors: ${claimed}`,
        issues: [
          { severity: 'info', code: 'crop', path: 'dimensions.crop', message: 'Crop did not run' },
          {
            severity: 'error',
            code: 'queue.output_claimed',
            path: 'output.path',
            message: claimed,
          },
        ],
      }),
    ]
    await mountTable()
    const problem = document.querySelector('[data-field="problem"]')
    expect(problem?.querySelector('[data-field="error"]')?.textContent?.trim()).toBe(
      `The job has errors: ${claimed}`,
    )
    expect(
      [...(problem?.querySelectorAll('li') ?? [])].map((li) => li.textContent?.trim()),
    ).toEqual(['Note: Crop did not run'])
    expect(problem?.textContent?.split(claimed)).toHaveLength(2)
  })

  it('says that the queue is empty and links to the workspace', async () => {
    await mountTable()
    const empty = document.querySelector('[data-state="empty"]')
    expect(empty?.textContent).toContain('The queue is empty')
    expect(empty?.querySelector('a')?.getAttribute('href')).toBe('/')
  })
})
