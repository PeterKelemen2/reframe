import type { Page } from '@playwright/test'

import { openApp, openFile } from './support/app'
import { expect, test } from './support/test'

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

test('the workspace with a file open is one window high', async ({ page }) => {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')

  await expect(page.locator('[data-card="tracks"] .summary-track').first()).toBeVisible()
  await expectOneWindowHigh(page, 'Summary')

  await page.getByRole('tab', { name: 'Audio' }).click()
  const rows = page.locator('[data-tab="audio"] .track-row')
  await expect(rows.first()).toBeVisible()
  await expect(page.locator('[data-tab="audio"] .track-table').first()).toBeVisible()
  await expectOneWindowHigh(page, 'Audio')
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
