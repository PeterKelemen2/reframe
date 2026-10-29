import { flushPromises, type VueWrapper } from '@vue/test-utils'
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { useQueueStore } from '@/stores/queue'

import QueueSection from './QueueSection.vue'
import { mountSettings, refusal, systemInfo } from './testing'

globalThis.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }) as unknown as MediaQueryList

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountQueue(mode: 'web' | 'desktop' = 'web') {
  const result = await mountSettings(QueueSection, { info: systemInfo({ mode }) })
  mounted.push(result.wrapper)
  const queue = useQueueStore()
  queue.setWhenDone = vi.fn<() => Promise<void>>(async () => undefined)
  const whenDone = () =>
    result.wrapper.findAllComponents(Select).find((c) => c.attributes('data-field') === 'when-done')
  const parallel = () => result.wrapper.findComponent(InputNumber)
  return { ...result, queue, whenDone, parallel }
}

function disabledOf(select: ReturnType<Awaited<ReturnType<typeof mountQueue>>['whenDone']>) {
  return ((select?.props('options') ?? []) as { value: string; disabled: boolean }[])
    .filter((option) => option.disabled)
    .map((option) => option.value)
}

describe('the Queue section', () => {
  it('sets when done through the queue, which also cancels another countdown', async () => {
    const { whenDone, queue, server } = await mountQueue()
    whenDone()?.vm.$emit('update:modelValue', 'sleep')
    await flushPromises()
    expect(queue.setWhenDone).toHaveBeenCalledWith('sleep')
    expect(server.patches).toEqual([])
  })

  it('shows quitting as the desktop app only in web mode', async () => {
    const web = await mountQueue('web')
    expect(disabledOf(web.whenDone())).toEqual(['quit'])
    web.wrapper.unmount()
    mounted.splice(0)
    const desktop = await mountQueue('desktop')
    expect(disabledOf(desktop.whenDone())).toEqual([])
  })

  it('shows a refused when-done value at its field', async () => {
    const { whenDone, queue, wrapper } = await mountQueue()
    queue.setWhenDone = vi.fn<() => Promise<void>>(async () => {
      throw new ApiError(503, { type: 'about:blank', title: 'Busy', status: 503, code: 'busy' })
    })
    whenDone()?.vm.$emit('update:modelValue', 'notify')
    await flushPromises()
    expect(wrapper.find('.rf-field__issue').text()).toContain('Busy')
  })

  it('saves the number of parallel jobs, and shows a refused number at its field', async () => {
    const { parallel, server, wrapper } = await mountQueue()
    parallel().vm.$emit('update:modelValue', 3)
    await flushPromises()
    expect(server.document.queue?.parallel_jobs).toBe(3)

    server.refuse = () =>
      new Response(
        JSON.stringify({
          type: 'about:blank',
          title: 'Not valid',
          status: 422,
          code: 'settings.invalid',
          issues: [
            {
              severity: 'error',
              code: 'settings.invalid',
              path: 'queue.parallel_jobs',
              message: 'Input should be less than or equal to 16',
              fixes: [],
            },
          ],
        }),
        { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
      )
    parallel().vm.$emit('update:modelValue', 99)
    await flushPromises()
    expect(wrapper.find('.rf-field__issue').text()).toContain('less than or equal to 16')
    expect(parallel().props('modelValue')).toBe(99)
    expect(server.document.queue?.parallel_jobs).toBe(3)
  })

  it('keeps the saved number when the field is emptied', async () => {
    const { parallel, server } = await mountQueue()
    parallel().vm.$emit('update:modelValue', null)
    await flushPromises()
    expect(server.patches).toEqual([])
  })

  it('switches sleep inhibit and notifications at once', async () => {
    const { wrapper, server } = await mountQueue()
    await wrapper.find('[data-field="sleep-inhibit"] input').trigger('change')
    await wrapper.find('[data-field="notifications"] input').trigger('change')
    await flushPromises()
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/queue/sleep_inhibit', value: false }],
      [{ op: 'replace', path: '/queue/notifications', value: false }],
    ])
  })

  it('names the reason of a refusal without issues', async () => {
    const { wrapper, server } = await mountQueue()
    server.refuse = () => refusal(403, 'settings.forbidden', 'Not here')
    await wrapper.find('[data-field="notifications"] input').trigger('change')
    await flushPromises()
    expect(wrapper.find('.rf-field__issue').text()).toContain('Not here')
  })
})
