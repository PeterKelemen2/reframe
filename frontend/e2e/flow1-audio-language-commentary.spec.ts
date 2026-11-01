import { openApp, openFile, probeFile, readQueue, waitForStore } from './support/app'
import { expect, test } from './support/test'

// Named, so a change of the default preset does not change this flow.
const PRESET = 'h264-mkv-1080p'
// multitrack.mkv's English stereo track.
const TRACK = 1

test('an audio language and the commentary flag set in the editor are in the encoded file', async ({
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
  const toggle = block.locator('[data-action="metadata-toggle"]')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')

  // The flow waits for controls only; the probe at the end says if the edits reached the file.
  // The language button's name is its label and value, so only its start is matched.
  await block.getByRole('button', { name: /^Language / }).click()
  const picker = page.getByRole('dialog', { name: 'Choose a language' })
  await picker.getByRole('combobox', { name: 'Search languages' }).fill('Hungarian')
  const hungarian = picker.getByRole('option').filter({ hasText: 'Hungarian' })
  await expect(hungarian).toHaveAttribute('data-tag', 'hu')
  await hungarian.click()
  await expect(picker).toBeHidden()

  await block.getByRole('switch', { name: 'Commentary', exact: true }).click()

  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.getByText('Added to the queue')).toBeVisible()
  await expect.poll(async () => (await ownJob())?.state).toBe('waiting')

  await page.getByRole('button', { name: 'Start', exact: true }).click()
  await expect.poll(async () => (await ownJob())?.state, { timeout: 60_000 }).toBe('done')
  const output = (await ownJob())?.output_path
  expect(output, 'the finished job names its output').toBeTruthy()

  const probed = await probeFile(request, output as string)
  const tracks = (probed.audio ?? []).map((track) => ({
    language: track.language,
    language_ietf: track.language_ietf,
    title: track.title,
    default: track.disposition?.default,
    commentary: track.disposition?.comment,
  }))
  expect(tracks).toEqual([
    {
      language: 'jpn',
      language_ietf: null,
      title: 'Japanese 5.1',
      default: true,
      commentary: false,
    },
    {
      language: 'hun',
      language_ietf: null,
      title: 'English Stereo',
      default: false,
      commentary: true,
    },
    {
      language: 'eng',
      language_ietf: null,
      title: "Director's Commentary",
      default: false,
      commentary: true,
    },
  ])
})
