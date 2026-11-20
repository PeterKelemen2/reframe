import { openApp, openFile, readQueue, waitForStore } from './support/app'
import { expect, test } from './support/test'

test('Start on a waiting job runs that job only', async ({ page, request }) => {
  const before = await readQueue(request)
  expect(before.processing).toBe(false)
  const known = new Set(before.jobs.map((job) => job.id))
  const ownJobs = async () => (await readQueue(request)).jobs.filter((job) => !known.has(job.id))

  await openApp(page)
  const add = async (count: number) => {
    await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
    await expect.poll(async () => (await ownJobs()).length).toBe(count)
  }
  await openFile(page, 'multitrack.mkv')
  await add(1)
  const [held] = await ownJobs()
  const letterbox = held!.settings.source.path.replace(/multitrack\.mkv$/, 'letterbox.mkv')
  await openFile(page, 'letterbox.mkv')
  await page.locator(`.source-item[data-path="${letterbox}"]`).click()
  await waitForStore(page, 'editor', 'job.source.path', letterbox)
  await add(2)
  const started = (await ownJobs()).find((job) => job.id !== held!.id)
  expect(started?.settings.source.path).toBe(letterbox)

  await page.locator('.nav-rail').getByRole('link', { name: 'Queue' }).click()
  const row = (id: string) => page.locator('tr', { has: page.locator(`[data-job="${id}"]`) })
  await expect(row(held!.id).locator('[data-action="start"]')).toBeVisible()
  const start = row(started!.id).getByRole('button', { name: 'Start letterbox.mkv' })
  await start.click()

  const state = async (id: string) => (await ownJobs()).find((job) => job.id === id)?.state
  await expect.poll(() => state(started!.id), { timeout: 60_000 }).toBe('done')
  expect(await state(held!.id)).toBe('waiting')
  // The run of the started job has ended: the queue is idle and the other job still offers Start.
  await expect.poll(async () => (await readQueue(request)).processing).toBe(false)
  await expect(row(held!.id).locator('[data-action="start"]')).toBeVisible()
  await expect(row(started!.id).locator('[data-action="start"]')).toHaveCount(0)
})
