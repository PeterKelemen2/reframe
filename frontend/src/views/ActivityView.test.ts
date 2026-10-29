import { flushPromises } from '@vue/test-utils'
import SelectButton from 'primevue/selectbutton'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { job, mountQueue, queueDouble, resetQueue } from '@/components/queue/testing'
import { useActivityStore } from '@/stores/activity'

import ActivityView from './ActivityView.vue'

const queue = queueDouble()
vi.mock('@/stores/queue', () => ({ useQueueStore: () => queue }))

const mounted: { unmount(): void }[] = []

beforeEach(() => {
  resetQueue(queue)
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

const texts = () =>
  [...document.querySelectorAll('[data-view="activity"] li [data-field="text"]')].map((el) =>
    el.textContent?.trim(),
  )

async function mountView() {
  const result = await mountQueue(ActivityView, { path: '/activity' })
  mounted.push(result.wrapper)
  return result
}

describe('the activity view', () => {
  it('lists the session’s events newest first, filtered by kind, and clears them', async () => {
    const { wrapper } = await mountView()
    expect(document.querySelector('[data-state="empty"]')?.textContent?.trim()).toBe(
      'Nothing has happened yet in this session.',
    )
    queue.jobs = [job('movie')]
    const activity = useActivityStore()
    activity.record({ type: 'job.state', job_id: 'movie', previous: null, state: 'waiting' })
    activity.record({ type: 'queue.processing', processing: true, only: null, reason: 'start' })
    activity.record({
      type: 'job.state',
      job_id: 'movie',
      previous: 'running',
      state: 'failed',
      error: 'x265 broke',
    })
    await flushPromises()
    expect(texts()).toEqual([
      'movie.mkv failed',
      'The queue was started: it takes every waiting job',
      'movie.mkv was added to the queue',
    ])
    expect(document.querySelector('[data-field="detail"]')?.textContent?.trim()).toBe('x265 broke')

    wrapper.findComponent(SelectButton).vm.$emit('update:modelValue', 'queue')
    await flushPromises()
    expect(texts()).toEqual(['The queue was started: it takes every waiting job'])
    wrapper.findComponent(SelectButton).vm.$emit('update:modelValue', 'warnings')
    await flushPromises()
    expect(document.querySelector('[data-state="empty"]')?.textContent?.trim()).toBe(
      'No entries of this kind.',
    )

    document.querySelector<HTMLButtonElement>('[data-action="clear"]')?.click()
    await flushPromises()
    expect(activity.entries).toEqual([])
  })

  it('names a job that was never seen by a short id', async () => {
    await mountView()
    useActivityStore().record({
      type: 'job.state',
      job_id: '0123456789abcdef',
      previous: 'waiting',
      state: 'running',
    })
    await flushPromises()
    expect(texts()).toEqual(['job 01234567 started'])
  })
})
