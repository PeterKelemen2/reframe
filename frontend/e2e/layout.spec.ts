import type { Locator, Page } from '@playwright/test'

import { openApp, openFile, waitForStore } from './support/app'
import { expect, test } from './support/test'

// Its encoder is unavailable under the fake FFmpeg: its issue's fix has a long label.
const UNAVAILABLE_PRESET = 'h265-nvenc-1080p'

/** The page's own scroll height and position next to the window's height. */
function pageScroll(page: Page): Promise<{ height: number; top: number; window: number }> {
  return page.evaluate(() => {
    // This file is type-checked without the DOM library.
    const doc = Reflect.get(globalThis, 'document') as object
    const root = Reflect.get(doc, 'scrollingElement') as { scrollHeight: number; scrollTop: number }
    const window = Reflect.get(globalThis, 'innerHeight') as number
    return { height: root.scrollHeight, top: root.scrollTop, window }
  })
}

/**
 * The shell is one window high and every column scrolls by itself: a taller page lets the wheel
 * or a scroll into view move the whole shell (rail, header, status bar) out of the window.
 */
async function expectOneWindowHigh(page: Page, where: string): Promise<void> {
  const { height, top, window } = await pageScroll(page)
  expect(height, `${where}: the page's height`).toBeLessThanOrEqual(window)
  expect(top, `${where}: the page's scroll position`).toBe(0)
}

/** Each icon in `buttons` is drawn at the width it asks for. */
async function expectIconsAtFullSize(buttons: Locator, where: string): Promise<void> {
  const icons = await buttons.locator('svg').all()
  expect(icons.length, `${where}: icons`).toBeGreaterThan(0)
  const sizes = await Promise.all(
    icons.map(async (icon) => ({
      asked: Number(await icon.getAttribute('width')),
      drawn: (await icon.boundingBox())?.width,
    })),
  )
  for (const { asked, drawn } of sizes) {
    expect(drawn, `${where}: an icon of ${asked} px`).toBeGreaterThanOrEqual(asked - 0.5)
  }
}

test('the workspace with a file open is one window high, its icons at full size', async ({
  page,
}) => {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')

  await expect(page.locator('[data-card="tracks"] .summary-track').first()).toBeVisible()
  await expectOneWindowHigh(page, 'Summary')

  await page.getByRole('tab', { name: 'Audio' }).click()
  const rows = page.locator('[data-tab="audio"] .track-row')
  await expect(rows.first()).toBeVisible()
  await expect(page.locator('[data-tab="audio"] .track-table').first()).toBeVisible()
  await expectOneWindowHigh(page, 'Audio')
  await expectIconsAtFullSize(page.locator('.workspace__header .p-button'), 'the header')
  await expectIconsAtFullSize(rows.first().locator('.track-row__buttons'), 'a track row')
})

test('Settings stays one window high after a section link', async ({ page }) => {
  await openApp(page)
  await page.locator('.nav-rail').getByRole('link', { name: 'Settings' }).click()
  const appearance = page.locator('[data-section="appearance"]')
  await expect(appearance).toBeAttached()
  await expectOneWindowHigh(page, 'Settings')

  await page.locator('[data-section-link="appearance"]').click()
  await expect(appearance).toBeInViewport()
  await expect(page.locator('.nav-rail')).toBeInViewport()
  await expectOneWindowHigh(page, 'Settings after a section link')
})

test('the queue view with a job is one window high', async ({ page }) => {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await expect(page.locator('.status-bar__add')).toBeEnabled()
  await page.locator('.status-bar__add').click()
  await expect(page.getByText('Added to the queue')).toBeVisible()

  await page.locator('.nav-rail').getByRole('link', { name: 'Queue' }).click()
  await expect(page.locator('[data-view="queue"] tbody tr').first()).toBeVisible()
  await expectOneWindowHigh(page, 'Queue')
})

test("the status bar's issue list keeps a message readable beside a long fix", async ({ page }) => {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await page.locator('.preset-picker__trigger').click()
  await page.locator(`.preset-picker__list [data-preset="${UNAVAILABLE_PRESET}"]`).click()
  await waitForStore(page, 'editor', 'presetId', UNAVAILABLE_PRESET)

  await page.locator('.validation-summary').click()
  const issue = page
    .locator('.validation-summary__list .rf-issue')
    .filter({ has: page.locator('.rf-issue__fix', { hasText: 'closest match' }) })
  await expect(issue).toHaveCount(1)
  const message = await issue.locator('.rf-issue__message').boundingBox()
  expect(message?.width, 'the message beside the fix').toBeGreaterThan(200)
})
