import { openApp, openFile, readQueue, waitForStore } from './support/app'
import { expect, test } from './support/test'

// The fake FFmpeg (fake-ffmpeg.json) fails every hardware test encode, NVENC with the captured
// "Cannot load libcuda.so.1", so hevc_nvenc is unavailable and its closest available match is
// libx265, the software end of its fallback chain.
const PRESET = 'h265-nvenc-1080p'
const PRESET_NAME = 'H.265 NVENC 1080p'
const REASON = 'NVIDIA driver not found'

test('a preset with an unavailable encoder: banner, the closest match, queue', async ({
  page,
  request,
}) => {
  const known = new Set((await readQueue(request)).jobs.map((job) => job.id))
  const ownJob = async () => (await readQueue(request)).jobs.find((job) => !known.has(job.id))

  await openApp(page)
  await openFile(page, 'multitrack.mkv')

  await page.locator('.preset-picker__trigger').click()
  await page.locator(`.preset-picker__list [data-preset="${PRESET}"]`).click()
  await expect(page.locator('.preset-picker__trigger [data-field="preset"]')).toHaveText(
    PRESET_NAME,
  )
  await waitForStore(page, 'editor', 'presetId', PRESET)

  await page.getByRole('tab', { name: 'Video' }).click()
  const banner = page.locator('.encoder-banner')
  await expect(banner).toHaveAttribute('role', 'alert')
  await expect(banner).toContainText(`Preset ${PRESET_NAME} uses hevc_nvenc`)
  await expect(banner).toContainText(REASON)
  await expect(page.locator('.status-bar__add')).toBeDisabled()

  await page.getByRole('tab', { name: 'Summary' }).click()
  const errors = page.locator('.summary-issues [data-severity="error"]')
  await expect(errors.filter({ hasText: 'hevc_nvenc' })).not.toHaveCount(0)

  await page.getByRole('tab', { name: 'Video' }).click()
  const fix = banner.locator('.encoder-banner__fix').filter({ hasText: /^Use libx265 \(closest/ })
  await expect(fix).toHaveCount(1)
  await fix.click()
  await waitForStore(page, 'editor', 'job.video.encoder', 'libx265')
  await expect(banner).toHaveCount(0)
  await expect(page.locator('.encoder-picker [role="combobox"]')).toContainText('libx265')

  await page.getByRole('tab', { name: 'Summary' }).click()
  await expect(errors).toHaveCount(0)
  await expect(page.locator('.status-bar__add')).toBeEnabled()

  await page.locator('.status-bar__add').click()
  await expect(page.getByText('Added to the queue')).toBeVisible()
  const job = await ownJob()
  expect(job?.state).toBe('waiting')
  expect(job?.settings.preset_id).toBe(PRESET)
  expect(job?.settings.video?.encoder).toBe('libx265')

  await page.locator('.status-bar__start').click()
  await expect.poll(async () => (await ownJob())?.state, { timeout: 60_000 }).toBe('done')
})
