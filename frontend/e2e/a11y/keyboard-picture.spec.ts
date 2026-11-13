import type { Locator, Page } from '@playwright/test'

import { expect, test } from '../support/test'
import { openAdvanced, openTab, showTab } from './steps'

type Edge = 'top' | 'bottom' | 'left' | 'right'

/** Whether the focus is in the element (this file is type-checked without the DOM library). */
function holdsFocus(element: { contains(other: unknown): boolean }): boolean {
  const doc = Reflect.get(globalThis, 'document') as { activeElement: unknown }
  return element.contains(doc.activeElement)
}

/** letterbox.mkv on Dimensions in manual crop, chosen with the keyboard (22 / 24 / 0 / 0). */
async function manualCrop(page: Page): Promise<void> {
  await openTab(page, 'letterbox.mkv', 'Dimensions')
  await expect(page.locator('[data-line="detection"]')).toContainText('Detected')
  const manual = page
    .locator('[data-control="crop-mode"]')
    .getByRole('button', { name: 'Manual', exact: true })
  await manual.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('[data-crop-handle="top"]')).toHaveAttribute('aria-valuenow', '22')
}

/** The crop that the tab's inputs show. */
async function shownCrop(page: Page): Promise<Record<Edge, number>> {
  const read = async (edge: Edge) =>
    Number(await page.locator(`input[data-edge="${edge}"]`).inputValue())
  return {
    top: await read('top'),
    bottom: await read('bottom'),
    left: await read('left'),
    right: await read('right'),
  }
}

test('the crop handles move to either end with Home and End, and a page with Page Up and Down', async ({
  page,
}) => {
  await manualCrop(page)
  const handle = (edge: Edge) => page.locator(`[data-crop-handle="${edge}"]`)
  const scroller = page.locator('.preview-panel__content')
  const scrolled = () => scroller.evaluate((element) => element.scrollTop)
  const before = await scrolled()

  await handle('top').focus()
  await page.keyboard.press('End')
  // As far as the crop can go with one chroma row left above the bottom crop.
  expect(await shownCrop(page)).toEqual({ top: 154, bottom: 24, left: 0, right: 0 })
  await expect(handle('top')).toHaveAttribute('aria-valuenow', '154')
  await expect(handle('top')).toHaveAttribute('aria-valuemax', '154')
  await page.keyboard.press('Home')
  await expect(handle('top')).toHaveAttribute('aria-valuenow', '0')
  await page.keyboard.press('PageDown')
  await expect(handle('top')).toHaveAttribute('aria-valuenow', '16')
  await page.keyboard.press('PageUp')
  await expect(handle('top')).toHaveAttribute('aria-valuenow', '0')

  await handle('bottom').focus()
  await page.keyboard.press('PageUp')
  await expect(handle('bottom')).toHaveAttribute('aria-valuenow', '40')

  await handle('left').focus()
  await page.keyboard.press('PageUp')
  await expect(handle('left')).toHaveAttribute('aria-valuenow', '16')
  await page.keyboard.press('End')
  await expect(handle('left')).toHaveAttribute('aria-valuenow', '318')
  await page.keyboard.press('Home')
  expect(await shownCrop(page)).toEqual({ top: 0, bottom: 40, left: 0, right: 0 })

  // The keys moved the edges: the panel kept its scroll and its frame, and the handle its focus.
  expect(await scrolled()).toBe(before)
  await expect(page.locator('[data-crop-magnifier] [data-frame-label]')).toHaveText('Frame 1 / 10')
  await expect(handle('left')).toBeFocused()
})

test('the crop check dialog keeps the focus inside and gives it back on Escape', async ({
  page,
}) => {
  await manualCrop(page)
  const opener = page.getByRole('button', { name: 'Check crop on all frames' })
  await opener.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Crop on all frames' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused()
  for (let press = 0; press < 12; press += 1) {
    // oxlint-disable-next-line eslint/no-await-in-loop -- each Tab follows the last
    await page.keyboard.press('Tab')
    // oxlint-disable-next-line eslint/no-await-in-loop -- read after this Tab
    expect(await dialog.evaluate(holdsFocus)).toBe(true)
  }
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(opener).toBeFocused()
})

/** Presses Enter on the Summary's link to `path`, reached from the tab with the keyboard. */
async function follow(page: Page, path: string): Promise<void> {
  await showTab(page, 'Summary')
  const link = page.locator(`[data-panel="summary"] button[data-path="${path}"]`).first()
  await link.focus()
  await page.keyboard.press('Enter')
}

async function expectFocusIn(locator: Locator): Promise<void> {
  await expect.poll(() => locator.evaluate(holdsFocus)).toBe(true)
}

test('a Summary link takes the keyboard to its field', async ({ page }) => {
  await openTab(page, 'multitrack.mkv', 'Summary')
  await expect(page.locator('[data-card="source"]')).toBeVisible()

  await follow(page, 'dimensions')
  await expectFocusIn(page.locator('[data-panel="dimensions"]'))

  await follow(page, 'filters.deinterlace')
  await expect(page.getByRole('switch', { name: 'Deinterlace' })).toBeFocused()

  await follow(page, 'video.preset')
  await expect(page.getByRole('slider', { name: 'Speed preset' })).toBeFocused()

  // The pressed button of the group, not the first one.
  await follow(page, 'video.bit_depth')
  await expect(page.getByRole('button', { name: '10-bit', exact: true })).toBeFocused()

  // The advanced options open, with the focus on their toggle.
  const toggle = page.locator('[data-section="advanced"] .rf-section__toggle')
  await expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await follow(page, 'video.advanced')
  await expect(toggle).toBeFocused()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  await openAdvanced(page)

  await follow(page, 'audio[1]')
  await expectFocusIn(page.locator('[data-panel="audio"]'))
})
