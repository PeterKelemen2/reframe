import { openApp, openFile, probeFile, readQueue, waitForStore } from './support/app'
import { expect, test } from './support/test'

const PRESET = 'h264-mkv-1080p'
// multitrack.mkv's English stereo track.
const TRACK = 1
const TEMPLATE = '{lang_name} {channels} {codec}'

test('a name template typed into a track is filled in: Summary, command and file', async ({
  page,
  request,
}) => {
  const known = new Set((await readQueue(request)).jobs.map((job) => job.id))
  const ownJob = async () => (await readQueue(request)).jobs.find((job) => !known.has(job.id))

  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await page.locator('.preset-picker__trigger').click()
  await page.locator(`.preset-picker__list [data-preset="${PRESET}"]`).click()
  await waitForStore(page, 'editor', 'presetId', PRESET)

  await page.getByRole('tab', { name: 'Audio' }).click()
  const row = page.locator(`[data-list="audio"] [data-path="audio[${TRACK}]"]`)
  const block = row.locator(`[data-metadata="audio[${TRACK}].metadata"]`)
  await block.locator('[data-action="metadata-toggle"]').click()
  const name = block.locator(`.rf-field[data-path="audio[${TRACK}].metadata.name"] input`)
  await name.fill(TEMPLATE)
  await name.blur()
  await waitForStore(page, 'editor', `job.audio.${TRACK}.metadata.name`, TEMPLATE)

  await page.getByRole('tab', { name: 'Summary' }).click()
  const shown = page.locator(
    `[data-card="tracks"] [data-path="audio[${TRACK}]"] .summary-track__name`,
  )
  await expect(shown).toHaveText(/^English 2\.0 \S+$/)
  const written = (await shown.textContent())!.trim()

  await page.getByRole('tab', { name: 'Video' }).click()
  await page.getByRole('button', { name: 'FFmpeg command' }).click()
  const command = page.getByLabel('The FFmpeg command of this job')
  await expect(command).toContainText(`title=${written}`)
  await expect(command).not.toContainText('{lang_name}')

  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.getByText('Added to the queue')).toBeVisible()
  await expect.poll(async () => (await ownJob())?.state).toBe('waiting')
  expect((await ownJob())?.settings.audio?.[TRACK]?.metadata?.name).toBe(TEMPLATE)
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  await expect.poll(async () => (await ownJob())?.state, { timeout: 60_000 }).toBe('done')

  const probed = await probeFile(request, (await ownJob())!.output_path as string)
  expect(probed.audio?.[TRACK]?.title).toBe(written)
})
