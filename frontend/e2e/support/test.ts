import { test as base, expect } from '@playwright/test'

import type { JobState, QueueJob } from '../../src/api/types'
import { queueAction, readQueue } from './app'

const ACTIVE = new Set<JobState>(['running', 'paused'])

/**
 * The tests of one browser project take turns on its server. Each test leaves the queue as it
 * found it: a job left behind would make the next test's job of the same file "also the output
 * of a job in the queue", and a started queue would run that job at once.
 */
export const test = base.extend<{ ownQueue: undefined }>({
  ownQueue: [
    async ({ request }, use) => {
      const before = await readQueue(request)
      const known = new Set(before.jobs.map((job) => job.id))
      const added = async (): Promise<QueueJob[]> =>
        (await readQueue(request)).jobs.filter((job) => !known.has(job.id))
      await use(undefined)

      if (!before.processing) await queueAction(request, 'post', '/api/queue/stop')
      const active = (await added()).filter((job) => ACTIVE.has(job.state))
      await Promise.all(
        active.map((job) => queueAction(request, 'post', `/api/queue/${job.id}/cancel`)),
      )
      await expect
        .poll(async () => (await added()).filter((job) => ACTIVE.has(job.state)).length)
        .toBe(0)
      const ended = await added()
      await Promise.all(ended.map((job) => queueAction(request, 'delete', `/api/queue/${job.id}`)))
    },
    { auto: true },
  ],
})

export { expect }
