import { openApp, openFile, probeFile, readQueue, waitForStore } from './support/app'
import { expect, test } from './support/test'

// Named, so the flow does not follow a change of the default preset: an MKV one that keeps the
// encode short with libx264.
const PRESET = 'h264-mkv-1080p'
// The English stereo track: the flow gives it a language and a flag that it does not have.
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

  // Between the edits and the probe the flow waits only for the controls: whether the edits
  // reached the file is for the probe to say. The trigger's name is its label and its value.
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
