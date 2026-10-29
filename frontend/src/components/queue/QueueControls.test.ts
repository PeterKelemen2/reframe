import { flushPromises } from '@vue/test-utils'
import Select from 'primevue/select'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import type { SystemInfo, WhenDone } from '@/api/types'

import PowerBanner from './PowerBanner.vue'
import QueueControls from './QueueControls.vue'
import { job, mountQueue, queueDouble, resetQueue } from './testing'
import WhenDoneSelect from './WhenDoneSelect.vue'

const queue = queueDouble()
const system = reactive({ info: { mode: 'web' } as Partial<SystemInfo> | null })
vi.mock('@/stores/queue', () => ({ useQueueStore: () => queue }))
vi.mock('@/stores/system', () => ({ useSystemStore: () => system }))

const mounted: { unmount(): void }[] = []

beforeEach(() => {
  resetQueue(queue)
  vi.clearAllMocks()
  system.info = { mode: 'web' }
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountIt(
  component: typeof QueueControls | typeof PowerBanner | typeof WhenDoneSelect,
) {
  const result = await mountQueue(component)
  mounted.push(result.wrapper)
  return result
}

const el = <T extends HTMLElement = HTMLButtonElement>(selector: string) => {
  const found = document.querySelector<T>(selector)
  if (!found) throw new Error(`no ${selector}`)
  return found
}
const text = (selector: string) => el(selector).textContent?.trim()

/** Presses a control whose action makes it unavailable; it keeps the focus, and does nothing again. */
async function pressTwice(action: string, run: () => Promise<void>): Promise<void> {
  const button = el(`[data-action="${action}"]`)
  button.focus()
  button.click()
  await flushPromises()
  expect(run).toHaveBeenCalledOnce()
  expect(document.activeElement).toBe(button)
  expect(button.disabled).toBe(false)
  expect(button.getAttribute('aria-disabled')).toBe('true')
  button.click()
  await flushPromises()
  expect(run).toHaveBeenCalledOnce()
}

describe('the run state and the global controls', () => {
  it('says that the queue is stopped and how many jobs wait for Start; Start starts every job', async () => {
    queue.jobs = [job('a', 'done'), job('b'), job('c')]
    await mountIt(QueueControls)
    expect(text('[data-field="run-state"]')).toBe('Stopped: 2 jobs wait for Start')
    queue.jobs = [job('b')]
    await flushPromises()
    expect(text('[data-field="run-state"]')).toBe('Stopped: 1 job waits for Start')
    expect(el('[data-action="stop"]').disabled).toBe(true)
    el('[data-action="start"]').click()
    await flushPromises()
    expect(queue.start).toHaveBeenCalledWith()
  })

  it('offers no Start while stopped with nothing waiting', async () => {
    queue.jobs = [job('a', 'done')]
    await mountIt(QueueControls)
    expect(text('[data-field="run-state"]')).toBe('Stopped')
    expect(el('[data-action="start"]').disabled).toBe(true)
  })

  it('offers Stop and no Start while every waiting job is taken', async () => {
    queue.jobs = [job('a', 'running'), job('b')]
    queue.processing = true
    await mountIt(QueueControls)
    expect(text('[data-field="run-state"]')).toBe('Running: 1 waiting job starts in turn')
    expect(el('[data-action="start"]').disabled).toBe(true)
    // Nothing left to take: the runner takes what is added next.
    queue.jobs = [job('a', 'running')]
    await flushPromises()
    expect(text('[data-field="run-state"]')).toBe('Running: jobs added now start in turn')
    el('[data-action="stop"]').click()
    await flushPromises()
    expect(queue.stop).toHaveBeenCalledOnce()
  })

  it("shows a run limited to another front end's jobs, and offers Start all to widen it", async () => {
    queue.jobs = [job('a', 'running'), job('b')]
    queue.processing = true
    queue.only = ['a', 'left-the-queue']
    await mountIt(QueueControls)
    expect(text('[data-field="run-state"]')).toBe(
      'Running only the jobs another front end started (1)',
    )
    expect(text('[data-action="start"]')).toBe('Start all')
    el('[data-action="start"]').click()
    await flushPromises()
    expect(queue.start).toHaveBeenCalledWith()
  })

  it('pauses all while a job runs and resumes all while one is paused', async () => {
    queue.jobs = [job('a', 'running')]
    await mountIt(QueueControls)
    expect(el('[data-action="resume-all"]').disabled).toBe(true)
    el('[data-action="pause-all"]').click()
    await flushPromises()
    expect(queue.pauseAll).toHaveBeenCalledOnce()
    queue.jobs = [job('a', 'paused')]
    await flushPromises()
    expect(el('[data-action="pause-all"]').disabled).toBe(true)
    el('[data-action="resume-all"]').click()
    await flushPromises()
    expect(queue.resumeAll).toHaveBeenCalledOnce()
  })

  it('cancels all only after the confirmation', async () => {
    queue.jobs = [job('a', 'running'), job('b'), job('c', 'done')]
    await mountIt(QueueControls)
    el('[data-action="cancel-all"]').click()
    await flushPromises()
    expect(text('.p-confirmdialog')).toContain('This cancels all 2 jobs')
    el('.p-confirmdialog-reject-button').click()
    await flushPromises()
    expect(queue.cancelAll).not.toHaveBeenCalled()
    el('[data-action="cancel-all"]').click()
    await flushPromises()
    el('.p-confirmdialog-accept-button').click()
    await flushPromises()
    expect(queue.cancelAll).toHaveBeenCalledOnce()
  })

  // A browser moves the focus of a button that turns disabled to the page.
  it('keeps the focus on Start and Pause all once their action has made them unavailable', async () => {
    queue.jobs = [job('a', 'running'), job('b')]
    queue.start.mockImplementationOnce(async () => {
      queue.processing = true
    })
    queue.pauseAll.mockImplementationOnce(async () => {
      queue.jobs = [job('a', 'paused'), job('b')]
    })
    await mountIt(QueueControls)
    await pressTwice('start', queue.start)
    await pressTwice('pause-all', queue.pauseAll)
    expect(queue.counts.paused).toBe(1)
  })

  it('offers no Cancel all when no job is open', async () => {
    queue.jobs = [job('a', 'done'), job('b', 'failed')]
    await mountIt(QueueControls)
    expect(el('[data-action="cancel-all"]').disabled).toBe(true)
  })
})

async function options(): Promise<string[]> {
  el('[data-field="when-done"]').click()
  await flushPromises()
  return [...document.querySelectorAll('.p-select-option')].map(
    (option) =>
      `${option.textContent?.trim()}${option.getAttribute('aria-disabled') === 'true' ? ' (off)' : ''}`,
  )
}

describe('the when-done selector', () => {
  it('cannot choose Quit in web mode', async () => {
    await mountIt(WhenDoneSelect)
    expect(await options()).toEqual([
      'Do nothing',
      'Notify',
      'Quit Reframe (desktop app only) (off)',
      'Sleep',
      'Shut down',
    ])
  })

  it('can choose Quit in the desktop app', async () => {
    system.info = { mode: 'desktop' }
    await mountIt(WhenDoneSelect)
    expect((await options())[2]).toBe('Quit Reframe')
  })

  it('sets the choice through the queue', async () => {
    queue.whenDone = 'nothing'
    const { wrapper } = await mountIt(WhenDoneSelect)
    wrapper.findComponent(Select).vm.$emit('update:modelValue', 'sleep')
    await flushPromises()
    expect(queue.setWhenDone).toHaveBeenCalledWith('sleep' satisfies WhenDone)
    // Choosing what is already set sends nothing.
    wrapper.findComponent(Select).vm.$emit('update:modelValue', 'nothing')
    await flushPromises()
    expect(queue.setWhenDone).toHaveBeenCalledOnce()
  })
})

describe('the when-done countdown', () => {
  const countdown = {
    type: 'power.countdown',
    countdown_id: 'p1',
    action: 'sleep',
    phase: 'tick',
    seconds_left: 42,
  } as const

  it('shows the action and the seconds left, and cancels', async () => {
    queue.power = countdown
    await mountIt(PowerBanner)
    expect(text('[data-component="power-banner"] [role="alert"]')).toBe(
      'The queue is finished. When done: Sleep.',
    )
    expect(text('[data-field="seconds"]')).toBe('in 42 s')
    queue.power = { ...countdown, seconds_left: 41 }
    await flushPromises()
    expect(text('[data-field="seconds"]')).toBe('in 41 s')
    el('[data-action="cancel-power"]').click()
    await flushPromises()
    expect(queue.cancelPower).toHaveBeenCalledOnce()
  })

  it('has no Cancel once the action runs, and is gone without a countdown', async () => {
    queue.power = { ...countdown, phase: 'executing', seconds_left: 0 }
    await mountIt(PowerBanner)
    expect(text('[role="alert"]')).toBe('When done: Sleep now.')
    expect(document.querySelector('[data-action="cancel-power"]')).toBeNull()
    queue.power = null
    await flushPromises()
    expect(document.querySelector('[data-component="power-banner"]')).toBeNull()
  })
})
