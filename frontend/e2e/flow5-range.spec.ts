import { openApp, openFile, readQueue } from './support/app'
import { expect, test } from './support/test'

// chapters.mkv (5.021 s): 1 Opening 0–1 s, 2 Part One 1–2.5 s, 3 Part Two 2.5–4 s, 4 Credits.
// Chapters 2–3 are 1.0–4.0 s: the command seeks to 1 s and encodes 3 s.
const RANGE = { kind: 'chapters', start: 2, end: 3 }
const WHOLE = { label: 'Whole source', length: '0:05' }
const PICKED = { label: 'Chapters 2–3', length: '0:03' }
const TEMPLATE = '{main_title} {chapters}'

test('a chapter range: the header, the output name and the command follow it into the queue', async ({
  page,
  request,
}) => {
  const known = new Set((await readQueue(request)).jobs.map((job) => job.id))
  const ownJob = async () => (await readQueue(request)).jobs.find((job) => !known.has(job.id))

  await openApp(page)
  // The fixture is in the output root, which the e2e servers make a media root too.
  await openFile(page, 'chapters.mkv', 'output')

  const range = page.locator('.workspace__header [data-field="range"]')
  await expect(range).toHaveAttribute('data-kind', 'full')
  await expect(range.locator('[data-field="range-label"]')).toHaveText(WHOLE.label)
  await expect(range.locator('[data-field="range-length"]')).toHaveText(WHOLE.length)

  // A template with {chapters} first, so the name has to change when the range does.
  await page.getByRole('tab', { name: 'Summary' }).click()
  const output = page.locator('[data-card="output"]')
  const template = output.getByRole('combobox', { name: 'Template', exact: true })
  await template.fill(TEMPLATE)
  await template.blur()
  const name = output.locator('[data-testid="naming-result"]')
  await expect(name).toHaveText('chapters 1-4.mkv')

  await range.click()
  await expect(range).toHaveAttribute('aria-expanded', 'true')
  const popover = page.locator('.range-popover')
  await expect(popover).toBeVisible()
  await popover.getByRole('radio', { name: 'Chapters', exact: true }).check()

  const pick = async (path: string, option: RegExp) => {
    await popover.locator(`[data-path="${path}"]`).getByRole('combobox').click()
    await page.getByRole('option', { name: option }).click()
  }
  await pick('range.start', /^2 · Part One · /)
  await pick('range.end', /^3 · Part Two · /)

  await page.keyboard.press('Escape')
  await expect(popover).toBeHidden()
  await expect(range).toBeFocused()

  await expect(range).toHaveAttribute('data-kind', 'chapters')
  await expect(range.locator('[data-field="range-label"]')).toHaveText(PICKED.label)
  await expect(range.locator('[data-field="range-length"]')).toHaveText(PICKED.length)
  await expect(range).toHaveAccessibleName(new RegExp(`${PICKED.label}.*${PICKED.length}`))
  await expect(page.locator('[data-card="source"] [data-field="range"]')).toContainText(
    PICKED.label,
  )

  await expect(name).toHaveText('chapters 2-3.mkv')
  // A change from outside the naming editor leaves the job's path; the editor offers the new one.
  await output.getByRole('button', { name: 'Use this path' }).click()
  await expect(output.locator('[data-testid="job-path"]')).toHaveText(/\/chapters 2-3\.mkv$/)

  await page.getByRole('tab', { name: 'Video' }).click()
  await page.getByRole('button', { name: 'FFmpeg command' }).click()
  const command = page.getByLabel('The FFmpeg command of this job')
  const cut = async () => {
    const text = (await command.textContent()) ?? ''
    return {
      // The seek before the source's -i, and every output duration.
      seek: /-ss (\S+) -i \S*\/chapters\.mkv /.exec(text)?.[1] ?? null,
      durations: [...text.matchAll(/ -t (\S+)/g)].map((match) => match[1]),
    }
  }
  await expect.poll(cut).toEqual({ seek: '1', durations: ['3'] })

  await page.getByRole('button', { name: 'Add to queue', exact: true }).click()
  await expect(page.getByText('Added to the queue')).toBeVisible()
  await expect.poll(async () => (await ownJob())?.state).toBe('waiting')
  const queued = (await ownJob())?.settings
  expect(queued?.range).toEqual(RANGE)
  expect(queued?.output?.path).toMatch(/\/chapters 2-3\.mkv$/)
})
