import type { Locator, Page } from '@playwright/test'

import { expect, test } from '../support/test'
import { editSeason, openTab } from './steps'

// The keyboard paths of the tracks area that only a browser shows: native radio arrows, the
// focus traps of PrimeVue's overlays, and Tab order. Keyboard only after the set-up.

/** The element with the focus, as a locator the test can assert on. */
function focused(page: Page): Locator {
  return page.locator('*:focus')
}

/** Presses Tab until `target` has the focus. */
async function tabUntil(target: Locator): Promise<void> {
  await expect(async () => {
    await target.page().keyboard.press('Tab')
    await expect(target).toBeFocused({ timeout: 50 })
  }).toPass({ timeout: 30_000, intervals: [0] })
}

test('the Range modes keep the span while the arrows pass through them', async ({ page }) => {
  // chapters.mkv: 5.021 s at 25 fps, four chapters that end at 5 s.
  await openTab(page, 'chapters.mkv', 'Summary', 'output')
  const range = page.locator('.workspace__header [data-field="range"]')
  await range.focus()
  await page.keyboard.press('Enter')
  const popover = page.locator('.range-popover')
  await expect(popover).toBeVisible()
  await expect(popover.locator('[data-range-mode="full"]')).toBeFocused()

  // Each arrow checks the next mode, as native radios do.
  await page.keyboard.press('ArrowDown')
  await expect(range).toHaveAttribute('data-kind', 'chapters')
  await page.keyboard.press('ArrowDown')
  await expect(range).toHaveAttribute('data-kind', 'time')
  await page.keyboard.press('ArrowDown')
  await expect(range).toHaveAttribute('data-kind', 'frames')
  // Converted from the whole source, not from 0:00:00 – 0:00:05: the last 21 ms stay.
  await expect(range.locator('[data-field="range-label"]')).toHaveText('Frames 0 – end')

  // Tab round the popover comes back to the checked mode, never to another radio.
  const frames = popover.locator('[data-range-mode="frames"]')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(frames).toBeFocused()
  await expect(focused(page)).toHaveAttribute('data-range-mode', 'frames')

  await page.keyboard.press('Escape')
  await expect(popover).toBeHidden()
  await expect(range).toBeFocused()
})

test('the language picker reopens on the chosen language, and its list takes no Tab', async ({
  page,
}) => {
  await openTab(page, 'multitrack.mkv', 'Audio')
  const block = page.locator('[data-metadata="audio[1].metadata"]')
  await block.locator('[data-action="metadata-toggle"]').click()
  const trigger = block.locator('.language-picker__trigger')
  await trigger.focus()

  await page.keyboard.press('Enter')
  const search = page.getByRole('combobox', { name: 'Search languages' })
  await expect(search).toBeFocused()
  await page.keyboard.type('fren')
  await page.keyboard.press('Enter')
  await expect(trigger).toBeFocused()
  await expect(trigger).toHaveAttribute('data-tag', 'fr')

  await page.keyboard.press('ArrowDown')
  await expect(search).toBeFocused()
  await expect(search).toHaveValue('')
  const active = async () => {
    const id = await search.getAttribute('aria-activedescendant')
    return id === null ? null : page.locator(`[id="${id}"]`).getAttribute('data-tag')
  }
  await expect.poll(active).toBe('fr')

  // Tab goes round the search and the dialog's Close button: the list is driven from the search.
  const close = page.locator('.language-picker-dialog').getByRole('button', { name: 'Close' })
  await page.keyboard.press('Tab')
  await expect(close).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(search).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(trigger).toBeFocused()
  await expect(trigger).toHaveAttribute('data-tag', 'fr')
})

test('a matrix row with notes but no fix puts the focus on its notes', async ({ page }) => {
  await editSeason(page)
  await page.locator('.group-banner [data-action="check-group"]').click()
  const matrix = page.locator('.matrix-dialog')
  await expect(matrix.locator('tbody tr')).toHaveCount(12)
  // E11 lacks the dub: a near member, a warning and a note, nothing to fix.
  const e11 = matrix
    .locator('tbody tr')
    .filter({ has: page.locator('.matrix__label', { hasText: 'E11' }) })
  const file = e11.locator('.matrix__file')
  await expect(file).toHaveAttribute('data-status', 'warning')
  await tabUntil(file)

  await page.keyboard.press('Enter')
  const popover = page.locator('.matrix-popover')
  await expect(popover).toBeVisible()
  const notes = popover.locator('summary')
  await expect(notes).toBeFocused()
  // The popover's focus trap keeps the focus on its one control.
  await page.keyboard.press('Tab')
  await expect(notes).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(popover.locator('details')).toHaveAttribute('open', '')

  await page.keyboard.press('Escape')
  await expect(popover).toBeHidden()
  await expect(matrix).toBeVisible()
  await expect(file).toBeFocused()
})
