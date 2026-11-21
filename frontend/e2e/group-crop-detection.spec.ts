import { copyFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'

import type { APIRequestContext, Page } from '@playwright/test'

import {
  changeSettings,
  mediaRoot,
  openApp,
  readQueue,
  readSettings,
  readTasks,
} from './support/app'
import { expect, test } from './support/test'

// letterbox.mkv's first half: bars of 22 and 24 rows, which the automatic crop takes.
const BARS = { top: 22, bottom: 24, left: 0, right: 0 }
const SAMPLES = '/preview/sample_frames'

/** `count` copies of letterbox.mkv as the episodes of `show`, in a folder of that name. */
async function season(request: APIRequestContext, show: string, count: number): Promise<string> {
  const root = await mediaRoot(request)
  const folder = join(root, show)
  mkdirSync(folder)
  for (let episode = 1; episode <= count; episode += 1) {
    const name = `${show} S01E${String(episode).padStart(2, '0')}.mkv`
    copyFileSync(join(root, 'letterbox.mkv'), join(folder, name))
  }
  return folder
}

/** Opens the folder `show` and edits its group; the banner is returned. */
async function editSeason(page: Page, show: string, count: number) {
  await page.getByRole('button', { name: 'Open folder…' }).click()
  const browser = page.locator('.file-browser-dialog')
  await browser.locator(`.file-browser__entry[data-name="${show}"]`).click()
  await expect(browser.locator('[data-role="crumb"][aria-current="location"]')).toHaveText(show)
  await browser.getByRole('button', { name: 'Choose this folder' }).click()
  await expect(browser).toBeHidden()
  const group = page.getByRole('tree').locator(`[data-group^="${show}"]`)
  await expect(group.locator('[data-field="count"]')).toHaveText(`${count} files`)
  await group.getByRole('button', { name: 'Edit group' }).click()
  const banner = page.locator('.group-banner')
  await expect(banner.locator('[data-field="title"]')).toContainText(`(${count} files)`)
  return banner
}

async function jobsOf(request: APIRequestContext, folder: string) {
  return (await readQueue(request)).jobs.filter((job) =>
    job.settings.source.path.startsWith(`${folder}/`),
  )
}

test('Add group to queue detects the crop of each file before it queues them', async ({
  page,
  request,
}) => {
  const folder = await season(request, 'Wide Show', 3)
  await openApp(page)
  const banner = await editSeason(page, 'Wide Show', 3)

  await banner.getByRole('button', { name: 'Add group to queue' }).click()
  await expect(page.getByText('Queued 3 jobs')).toBeVisible()
  await expect(banner.locator('[data-state="detecting-crop"]')).toHaveCount(0)
  const jobs = await jobsOf(request, folder)
  expect(jobs.map((job) => job.settings.dimensions?.crop)).toEqual(
    Array.from({ length: 3 }, () => ({ mode: 'auto', rect: BARS })),
  )
  const [task] = (await readTasks(request, 'batch_cropdetect')).slice(-1)
  expect(task?.state).toBe('done')
})

test.describe('a slow detection', () => {
  let samples: number | undefined

  test.beforeEach(async ({ request }) => {
    samples = (await readSettings(request)).preview?.sample_frames
    // Each file then takes seconds: Cancel comes while the first files are measured.
    await changeSettings(request, [{ op: 'replace', path: SAMPLES, value: 60 }])
  })

  test.afterEach(async ({ request }) => {
    await changeSettings(request, [{ op: 'replace', path: SAMPLES, value: samples ?? 10 }])
  })

  test('shows the file it measures, and Cancel queues nothing', async ({ page, request }) => {
    const folder = await season(request, 'Tall Show', 8)
    await openApp(page)
    const banner = await editSeason(page, 'Tall Show', 8)

    const queue = banner.getByRole('button', { name: 'Add group to queue' })
    await queue.click()
    const detection = banner.locator('[data-state="detecting-crop"]')
    await expect(detection.getByRole('status')).toHaveText(/^Detecting the crop: file [1-7] of 8$/)
    await expect(queue).toHaveAttribute('aria-busy', 'true')
    await detection.getByRole('button', { name: 'Cancel the crop detection' }).click()

    await expect(detection).toHaveCount(0)
    await expect(queue).not.toHaveAttribute('aria-busy')
    await expect(queue).toBeFocused()
    await expect
      .poll(async () => (await readTasks(request, 'batch_cropdetect')).at(-1)?.state)
      .toBe('cancelled')
    await expect(page.getByText(/^Queued \d+ jobs?$/)).toHaveCount(0)
    expect(await jobsOf(request, folder)).toEqual([])
  })
})
