import type { APIRequestContext, Page } from '@playwright/test'

import type { JobSettings, QueueJob } from '../src/api/types'
import { openApp, openFile, readQueue, waitForStore } from './support/app'
import { TOKEN } from './support/servers'
import { expect, test } from './support/test'

// The fake FFmpeg (fake-ffmpeg.json) fails every hardware test encode, so hevc_nvenc is
// unavailable. A job queued with it (here through the API, as if it was added before the
// encoder went away) fails at once with `encoder.unavailable` and the closest match.
const PRESET = 'h265-nvenc-1080p'

/**
 * Queues the editor's job through the API: the editor itself refuses a job whose encoder is
 * unavailable.
 */
async function queueEditorJob(page: Page, request: APIRequestContext): Promise<QueueJob[]> {
  const settings = await page.evaluate(() => {
    // This file is type-checked without the DOM library.
    const doc = Reflect.get(globalThis, 'document') as { querySelector(s: string): unknown }
    let value = doc.querySelector('#app')
    for (const key of ['__vue_app__', 'config', 'globalProperties', '$pinia', '_s']) {
      value = Reflect.get(value as object, key)
    }
    const editor = (value as Map<string, { job: unknown }>).get('editor')
    return JSON.parse(JSON.stringify(editor?.job)) as unknown
  })
  const added = await request.post('/api/queue', {
    headers: { Authorization: `Bearer ${TOKEN}` },
    data: { jobs: [settings as JobSettings] },
  })
  expect(added.status()).toBe(201)
  return (await added.json()) as QueueJob[]
}

test('a queued job whose encoder is unavailable: its state, its fixes, then it runs', async ({
  page,
  request,
}) => {
  const known = new Set((await readQueue(request)).jobs.map((job) => job.id))
  const ownJobs = async () => (await readQueue(request)).jobs.filter((job) => !known.has(job.id))

  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await page.locator('.preset-picker__trigger').click()
  await page.locator(`.preset-picker__list [data-preset="${PRESET}"]`).click()
  await waitForStore(page, 'editor', 'presetId', PRESET)
  await waitForStore(page, 'editor', 'job.video.encoder', 'hevc_nvenc')
  const added = await queueEditorJob(page, request)
  const [failed] = added
  expect(failed?.state).toBe('failed')

  await page.locator('.nav-rail').getByRole('link', { name: 'Queue' }).click()
  const row = page.locator('tr', { has: page.locator(`[data-job="${failed!.id}"]`) })
  await expect(row.locator('[data-field="state"]')).toHaveText('Failed — encoder unavailable')
  const fixes = page.getByRole('group', { name: 'Fixes for multitrack.mkv' })
  await expect(fixes.getByRole('button')).toHaveText([
    /^Use libx265 \(closest match/,
    'Choose encoder',
    'Check again',
  ])

  await fixes.getByRole('button', { name: /^Use libx265/ }).click()
  await expect.poll(async () => (await ownJobs()).map((job) => job.id)).not.toContain(failed!.id)
  const [fixed] = await ownJobs()
  expect(fixed?.state).toBe('waiting')
  expect(fixed?.settings.video?.encoder).toBe('libx265')
  await expect(fixes).toHaveCount(0)

  const fixedRow = page.locator('tr', { has: page.locator(`[data-job="${fixed!.id}"]`) })
  await fixedRow.locator('[data-action="start"]').click()
  await expect
    .poll(async () => (await ownJobs()).find((job) => job.id === fixed!.id)?.state, {
      timeout: 60_000,
    })
    .toBe('done')
})

test('Choose encoder opens the failed job at its encoder in the workspace', async ({
  page,
  request,
}) => {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await page.locator('.preset-picker__trigger').click()
  await page.locator(`.preset-picker__list [data-preset="${PRESET}"]`).click()
  await waitForStore(page, 'editor', 'job.video.encoder', 'hevc_nvenc')
  await queueEditorJob(page, request)

  await page.locator('.nav-rail').getByRole('link', { name: 'Queue' }).click()
  const fixes = page.getByRole('group', { name: 'Fixes for multitrack.mkv' })
  await fixes.getByRole('button', { name: 'Choose encoder' }).click()
  await expect(page.getByRole('tab', { name: 'Video', selected: true })).toBeVisible()
  await expect(page.locator('.encoder-banner')).toContainText('hevc_nvenc')
})
