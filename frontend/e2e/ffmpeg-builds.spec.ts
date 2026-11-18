import { choosePreset } from './a11y/steps'
import { openApp, openFile } from './support/app'
import { openFirstRun, withBuildMismatch, withoutFfmpeg } from './support/ffmpeg'
import { expect, test } from './support/test'

test('without FFmpeg, the first-run screen offers the builds of the manifest', async ({ page }) => {
  await withoutFfmpeg(page)
  await openFirstRun(page)
  const builds = page.locator('[data-build]')
  await expect(builds).toHaveCount(2)
  expect(await builds.evaluateAll((all) => all.map((el) => el.getAttribute('data-build')))).toEqual(
    ['default', 'compat'],
  )
  await expect(page.locator('[data-build="default"] input[type="radio"]')).toBeChecked()
  await expect(page.locator('[data-build="default"] [data-field="facts"]')).toContainText(
    'GPL-3.0-or-later',
  )
  await expect(page.locator('[data-build="default"] details a').first()).toBeHidden()
  await page.locator('[data-build="default"] details summary').click()
  await expect(page.locator('[data-build="default"] details a').first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Download', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Install from file' })).toBeEnabled()
  // A browser cannot name a program path on the server.
  await expect(page.locator('.first-run__choose')).toHaveCount(0)
})

test('a build mismatch: the banner offers another FFmpeg, which opens Settings → Tools with the notice', async ({
  page,
}) => {
  await withBuildMismatch(page)
  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await choosePreset(page, 'h265-nvenc-1080p')

  await page.getByRole('tab', { name: 'Summary' }).click()
  const issue = page.locator('.summary-issues .rf-issue').filter({ hasText: 'hevc_nvenc' })
  await expect(issue.getByRole('button', { name: 'Use another FFmpeg…' })).toBeVisible()

  await page.getByRole('tab', { name: 'Video' }).click()
  const banner = page.locator('.encoder-banner')
  await expect(banner).toContainText('NVIDIA driver too old')
  await banner.getByRole('button', { name: 'Use another FFmpeg…' }).click()

  await expect(page).toHaveURL(/#tools$/)
  const notice = page.locator('[data-section="tools"] [data-field="mismatch-notice"]')
  await expect(notice).toBeVisible()
  await expect(notice.locator('[data-encoder="hevc_nvenc"]')).toContainText(
    'NVENC needs driver 610.00 or newer',
  )
  await expect(page.locator('[data-section="tools"] [data-build="compat"]')).toBeVisible()
})
