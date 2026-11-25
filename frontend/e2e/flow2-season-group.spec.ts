import type { Locator, Page } from '@playwright/test'

import { CROP_DETECTION, changeSettings, openApp, readQueue, readSettings } from './support/app'
import { expect, test } from './support/test'

const FOLDER = 'Anime.Show.S01.BluRay.x264-GRP'
const GROUP = 'Anime Show S01'
const EPISODES = Array.from({ length: 12 }, (_, index) => `E${String(index + 1).padStart(2, '0')}`)
// The fixture's episode titles, E01 to E12, as its file names carry them.
const TITLES = [
  'Pilot',
  'Departure',
  'Storm',
  'Signal',
  'Echoes',
  'Harbor',
  'Embers',
  'Drift',
  'Lantern',
  'Tides',
  'Static',
  'Homecoming',
]
const TEMPLATE = '{name} - S{season:02}E{episode:02}< - {sub_title}>'
const SEPARATOR = '/output/naming/word_separator'

// Tall enough for the matrix's virtual scroller to render all twelve rows at once.
test.use({ viewport: { width: 1600, height: 1200 } })

let separator: string | undefined

test.beforeEach(async ({ request }) => {
  separator = (await readSettings(request)).output?.naming?.word_separator
})

test.afterEach(async ({ request }) => {
  await changeSettings(request, [{ op: 'replace', path: SEPARATOR, value: separator ?? 'keep' }])
})

/** Picks `option` in the drop-down labelled `label` inside `scope`. */
async function choose(page: Page, scope: Locator, label: string, option: string): Promise<void> {
  await scope.getByRole('combobox', { name: label, exact: true }).click()
  // Bitrates are written with a no-break space before the unit.
  const name = new RegExp(`^${option.replaceAll(' ', '\\s')}$`)
  await page.getByRole('option', { name }).click()
}

/** Sets one output track's encoder, a 5.1 mixdown, its bitrate and its name. */
async function editAudio(
  page: Page,
  index: number,
  encoder: string,
  bitrate: string,
  name: string,
): Promise<void> {
  const row = page.locator(`[data-list="audio"] [data-path="audio[${index}]"]`)
  await choose(page, row, 'Encoder', encoder)
  await choose(page, row, 'Mixdown', '5.1')
  await choose(page, row, 'Bitrate', bitrate)
  await rename(row.locator(`[data-metadata="audio[${index}].metadata"]`), name)
}

async function rename(block: Locator, name: string): Promise<void> {
  await block.locator('[data-action="metadata-toggle"]').click()
  const field = block.getByRole('textbox', { name: 'Name', exact: true })
  await field.fill(name)
  await field.blur()
}

test('a season folder: edit the group, check the matrix, queue the group', async ({
  page,
  request,
}) => {
  const known = new Set((await readQueue(request)).jobs.map((job) => job.id))

  // The group's naming comes from Settings → Output, whose separator keeps the dots by default.
  await openApp(page)
  await page.getByRole('link', { name: 'Settings' }).click()
  await choose(page, page.locator('body'), 'Word separator', 'Space')
  await expect
    .poll(async () => (await readSettings(request)).output?.naming?.word_separator)
    .toBe('space')
  await page.getByRole('link', { name: 'Workspace' }).click()

  await page.getByRole('button', { name: 'Open folder…' }).click()
  const browser = page.locator('.file-browser-dialog')
  await browser.locator(`.file-browser__entry[data-name="${FOLDER}"]`).click()
  await expect(browser.locator('[data-role="crumb"][aria-current="location"]')).toHaveText(FOLDER)
  await browser.getByRole('button', { name: 'Choose this folder' }).click()
  await expect(browser).toBeHidden()

  const tree = page.getByRole('tree')
  const group = tree.locator(`[data-group="${GROUP}"]`)
  await expect(tree.locator('[aria-level="1"]')).toHaveCount(1)
  await expect(group.locator('[data-field="count"]')).toHaveText('12 files')
  // The tree is flat: the members follow their group's row, and this is the only group.
  const members = tree.locator('[aria-level="2"]')
  await expect(members.locator('.source-item__label')).toHaveText(EPISODES)
  // A row leads with its episode and title; the file name is its tooltip.
  await expect(members.locator('.source-item__episode')).toHaveText(
    EPISODES.map((episode, index) => `${episode} ${TITLES[index]}`),
  )
  // The open episode belongs to the group: the status bar's primary add is the season's.
  const statusBar = page.locator('.status-bar')
  await expect(statusBar.locator('.status-bar__add')).toHaveText('Add 12 episodes to queue')
  await expect(statusBar.locator('.status-bar__only')).toHaveText('Only E01')
  await expect(statusBar.locator('.status-bar__add-all')).toHaveText('Add all open files')
  await expect(members.and(page.locator('[data-match="near"]'))).toHaveCount(2)
  const e05 = members.filter({ hasText: 'E05' })
  await expect(e05).toHaveAttribute('data-match', 'near')
  await expect(e05.locator('[data-field="difference"]')).toHaveText(
    '1 extra track (eng AC-3 2.0 "Commentary")',
  )

  await group.getByRole('button', { name: 'Edit group' }).click()
  const banner = page.locator('.group-banner')
  await expect(banner.locator('[data-field="title"]')).toHaveText(
    `Editing group “${GROUP}” (12 files) — showing E01`,
  )

  await page.getByRole('tab', { name: 'Audio' }).click()
  await editAudio(page, 0, 'Opus', '448 kb/s', 'Japanese 5.1')
  await editAudio(page, 1, 'AC-3', '640 kb/s', 'English 5.1')
  // E01's subtitle flags are the example's already, so a flag change would derive nothing.
  await page.getByRole('tab', { name: 'Subtitles' }).click()
  await rename(
    page.locator('[data-list="subtitles"] [data-metadata="subtitles[1].metadata"]'),
    'Full subtitles',
  )

  await banner.getByRole('button', { name: 'Check group' }).click()
  const matrix = page.getByRole('dialog', { name: `Check group “${GROUP}”` })
  const rows = matrix.locator('tbody tr')
  const row = (episode: string) =>
    rows.filter({ has: page.locator('.matrix__label', { hasText: episode }) })
  const marks = rows.locator('.matrix__file .matrix__mark')
  const ok = (problems: Record<string, string>) => EPISODES.map((e) => problems[e] ?? '✓')
  await expect(rows.locator('.matrix__label')).toHaveText(EPISODES)
  // A mark is a drawn icon; `data-mark` holds the glyph `reframe batch` prints.
  const markOf = (cell: string) => row('E11').locator(`[data-cell="${cell}"] .matrix__mark`)
  const shownMarks = () => marks.evaluateAll((els) => els.map((el) => el.getAttribute('data-mark')))
  await expect.poll(shownMarks).toEqual(ok({ E05: '⚠', E11: '✗' }))
  await expect(markOf('audio:1')).toHaveAttribute('data-mark', '✗')
  await expect(markOf('subtitle:0')).toHaveAttribute('data-mark', '≈')

  await row('E11').locator('.matrix__file').click()
  await page.getByRole('button', { name: 'Make the rule optional' }).click()
  await expect(markOf('audio:1')).toHaveAttribute('data-mark', '–')
  await expect.poll(shownMarks).toEqual(ok({ E05: '⚠', E11: '⚠' }))
  await matrix.getByRole('button', { name: 'Close' }).click()
  await expect(matrix).toBeHidden()

  await page.getByRole('tab', { name: 'Summary' }).click()
  const output = page.locator('[data-card="output"]')
  const template = output.getByRole('combobox', { name: 'Template', exact: true })
  await template.fill(TEMPLATE)
  await template.blur()
  await expect(output.getByTestId('naming-result')).toHaveText('Anime Show - S01E01 - Pilot.mkv')

  await statusBar.getByRole('button', { name: 'Add 12 episodes to queue' }).click()
  await expect(page.getByText('Queued 12 jobs')).toBeVisible({ timeout: CROP_DETECTION })
  const jobs = (await readQueue(request)).jobs
    .filter((job) => !known.has(job.id))
    .toSorted((a, b) => a.position - b.position)
  expect(jobs.map((job) => job.settings.output?.path?.split('/').at(-1))).toEqual(
    EPISODES.map((episode, index) => `Anime Show - S01${episode} - ${TITLES[index]}.mkv`),
  )
  const audio = jobs.map((job) =>
    (job.settings.audio ?? []).map((track) => [
      track.encoder,
      track.mixdown,
      track.bitrate,
      track.metadata?.name,
    ]),
  )
  const both = [
    ['libopus', '5.1', 448, 'Japanese 5.1'],
    ['ac3', '5.1', 640, 'English 5.1'],
  ]
  expect(audio).toEqual(EPISODES.map((episode) => (episode === 'E11' ? both.slice(0, 1) : both)))
})
