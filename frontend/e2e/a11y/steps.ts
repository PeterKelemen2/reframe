import type { Page } from '@playwright/test'

import { openApp, openFile, waitForStore } from '../support/app'
import { expect } from '../support/test'

/** Opens the app and a file of the media root (or of `root`), and shows the editor's `tab`. */
export async function openTab(page: Page, file: string, tab: string, root?: string): Promise<void> {
  await openApp(page)
  await openFile(page, file, root)
  await showTab(page, tab)
}

export async function showTab(page: Page, tab: string): Promise<void> {
  const button = page.getByRole('tab', { name: tab, exact: true })
  await button.click()
  await expect(button).toHaveAttribute('aria-selected', 'true')
}

/** Picks a preset in the header's picker and waits until the editor has it. */
export async function choosePreset(page: Page, id: string): Promise<void> {
  await page.locator('.preset-picker__trigger').click()
  await page.locator(`.preset-picker__list [data-preset="${id}"]`).click()
  await waitForStore(page, 'editor', 'presetId', id)
}

/** Unfolds the Video tab's advanced options. */
export async function openAdvanced(page: Page): Promise<void> {
  const toggle = page.locator('[data-section="advanced"] .rf-section__toggle')
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
}

/** Follows a link of the navigation rail. */
export async function goTo(page: Page, link: string): Promise<void> {
  await page.locator('.nav-rail').getByRole('link', { name: link, exact: true }).click()
}

/** Opens the app and the season folder as one group. */
export async function openSeason(page: Page): Promise<void> {
  await openApp(page)
  await page.getByRole('button', { name: 'Open folder…' }).click()
  const browser = page.locator('.file-browser-dialog')
  await browser.locator('.file-browser__entry[data-name="Anime.Show.S01.BluRay.x264-GRP"]').click()
  await browser.getByRole('button', { name: 'Choose this folder' }).click()
  await expect(browser).toBeHidden()
  await expect(page.getByRole('tree').locator('[aria-level="1"]')).toHaveCount(1)
}

/** Opens the season folder and edits it as a group. */
export async function editSeason(page: Page): Promise<void> {
  await openSeason(page)
  await page.getByRole('tree').getByRole('button', { name: 'Edit group' }).click()
  await expect(page.locator('.group-banner')).toBeVisible()
  await expect(page.locator('.preset-picker__trigger')).toBeEnabled()
}
