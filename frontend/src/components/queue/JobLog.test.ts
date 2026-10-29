import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import type { JobLogChunk } from '@/api/types'
import { useToastStore } from '@/stores/toasts'
import QueueView from '@/views/QueueView.vue'

import JobLog from './JobLog.vue'
import { job, mountQueue, queueDouble, resetQueue } from './testing'

const queue = queueDouble()
const system = reactive({ info: { mode: 'web' } })
vi.mock('@/stores/queue', () => ({ useQueueStore: () => queue }))
vi.mock('@/stores/system', () => ({ useSystemStore: () => system }))
vi.mock('@/stores/editor', () => ({ useEditorStore: () => ({}) }))

globalThis.requestAnimationFrame ??= (callback: FrameRequestCallback) =>
  setTimeout(() => callback(0), 0) as unknown as number

let file = ''
const writeText = vi.fn<(text: string) => Promise<void>>(async () => {})
const mounted: { unmount(): void }[] = []

beforeEach(() => {
  resetQueue(queue)
  vi.clearAllMocks()
  file = ''
  queue.readLog.mockImplementation(async (_id: string, from = 0): Promise<JobLogChunk> => {
    const text = file.slice(from)
    return { text, next: from + text.length, more: false }
  })
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function settle(): Promise<void> {
  await flushPromises()
  // Past the next animation frame (jsdom runs them at 60 per second).
  await new Promise((resolve) => setTimeout(resolve, 40))
  await flushPromises()
}

const el = <T extends HTMLElement = HTMLButtonElement>(selector: string) => {
  const found = document.querySelector<T>(selector)
  if (!found) throw new Error(`no ${selector}`)
  return found
}

/** The scroller with a layout jsdom does not have: 1000 px of lines in a 100 px window. */
function scroller(): HTMLElement {
  const box = el<HTMLElement>('.job-log__scroller')
  Object.defineProperty(box, 'scrollHeight', { value: 1000, configurable: true })
  Object.defineProperty(box, 'clientHeight', { value: 100, configurable: true })
  return box
}

async function write(text: string): Promise<void> {
  file += text
  queue.logTicks = { a: (queue.logTicks.a ?? 0) + 1 }
  await settle()
}

describe('the job log viewer', () => {
  it('shows the whole log and copies all of it', async () => {
    queue.jobs = [job('a', 'done')]
    file = 'one\ntwo\nlast without newline'
    mounted.push((await mountQueue(JobLog, { props: { jobId: 'a' } })).wrapper)
    await settle()
    expect(el('[data-field="line-count"]').textContent?.trim()).toBe('3 lines')
    el('[data-action="copy"]').click()
    await settle()
    expect(writeText).toHaveBeenCalledWith('one\ntwo\nlast without newline')
    expect(useToastStore().items.map((toast) => toast.summary)).toEqual(['The log was copied'])
  })

  it('stays at the end while following, stops after a scroll up, and follows again', async () => {
    queue.jobs = [job('a', 'running')]
    file = 'one\n'
    mounted.push((await mountQueue(JobLog, { props: { jobId: 'a' } })).wrapper)
    await settle()
    const box = scroller()
    await write('two\n')
    expect(box.scrollTop).toBe(1000)
    expect(el('[data-action="follow"]').getAttribute('aria-pressed')).toBe('true')

    box.scrollTop = 0
    box.dispatchEvent(new Event('scroll'))
    await settle()
    expect(el('[data-action="follow"]').getAttribute('aria-pressed')).toBe('false')
    await write('three\n')
    expect(box.scrollTop).toBe(0)

    el('[data-action="follow"]').click()
    await settle()
    expect(box.scrollTop).toBe(1000)
    expect(el('[data-action="follow"]').getAttribute('aria-pressed')).toBe('true')
  })

  it('follows again when the user scrolls back to the end', async () => {
    queue.jobs = [job('a', 'running')]
    file = 'one\n'
    mounted.push((await mountQueue(JobLog, { props: { jobId: 'a' } })).wrapper)
    await settle()
    const box = scroller()
    box.scrollTop = 0
    box.dispatchEvent(new Event('scroll'))
    await settle()
    box.scrollTop = 900
    box.dispatchEvent(new Event('scroll'))
    await settle()
    expect(el('[data-action="follow"]').getAttribute('aria-pressed')).toBe('true')
  })

  it('returns the focus to the button that opened it', async () => {
    queue.jobs = [job('a', 'running')]
    file = 'one\n'
    mounted.push((await mountQueue(QueueView)).wrapper)
    const opener = el('[data-job="a"] [data-action="log"]')
    opener.focus()
    opener.click()
    await settle()
    expect(document.querySelector('[data-component="job-log"]')).not.toBeNull()
    el('[data-component="job-log"] .p-drawer-close-button').click()
    await settle()
    expect(document.activeElement).toBe(el('[data-job="a"] [data-action="log"]'))
  })
})
