import type { Page } from '@playwright/test'

import { openApp, openFile } from '../../support/app'
import { expect } from '../../support/test'
import { editSeason, openSeason, openTab, showTab } from '../steps'
import type { Screen } from '../types'

const PANEL = (tab: string) => `[data-panel="${tab}"]`
// Only one dialog is open on each of these screens.
const DIALOG = '.p-dialog'
const TRACK_METADATA = '[data-metadata="audio[1].metadata"]'

/** Unfolds the metadata block of multitrack.mkv's second audio track. */
async function trackMetadata(page: Page): Promise<void> {
  await openTab(page, 'multitrack.mkv', 'Audio')
  const toggle = page.locator(`${TRACK_METADATA} [data-action="metadata-toggle"]`)
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
}

/** A rule of the season group that E11 breaks: it has no second audio track. */
async function seasonWithError(page: Page): Promise<void> {
  await editSeason(page)
  await showTab(page, 'Audio')
  const row = page.locator('[data-list="audio"] [data-path="audio[1]"]')
  await row.getByRole('combobox', { name: 'Encoder', exact: true }).click()
  await page.getByRole('option', { name: 'AC-3', exact: true }).click()
}

export const screens: Screen[] = [
  {
    id: 'audio',
    area: 'tracks',
    region: PANEL('audio'),
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Audio')
      await expect(page.locator('[data-list="audio"] .track-row').first()).toBeVisible()
    },
  },
  {
    id: 'subtitles',
    area: 'tracks',
    region: PANEL('subtitles'),
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Subtitles')
      await page.locator('[data-action="add-external"]').click()
      const browser = page.locator('.file-browser-dialog')
      await browser.locator('.file-browser__entry[data-name="text-subs.en.srt"]').click()
      await browser.locator('[data-action="confirm"]').click()
      await expect(browser).toBeHidden()
      await expect(page.locator('[data-list="subtitles"] .track-row')).toHaveCount(4)
    },
  },
  {
    id: 'chapters',
    area: 'tracks',
    region: PANEL('chapters'),
    async setup(page) {
      await openTab(page, 'chapters.mkv', 'Chapters', 'output')
    },
  },
  {
    id: 'tags',
    area: 'tracks',
    region: PANEL('tags'),
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Tags')
    },
  },
  {
    id: 'track-metadata',
    area: 'tracks',
    region: TRACK_METADATA,
    setup: trackMetadata,
  },
  {
    id: 'bulk-edit',
    area: 'tracks',
    region: DIALOG,
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Audio')
      await page.locator('[data-select="all"]').click()
      await page.locator('[data-action="bulk-edit"]').click()
      await expect(page.locator(DIALOG)).toBeVisible()
    },
  },
  {
    id: 'language-picker',
    area: 'tracks',
    region: '.language-picker-dialog',
    async setup(page) {
      await trackMetadata(page)
      await page
        .locator(TRACK_METADATA)
        .getByRole('button', { name: /^Language / })
        .click()
      await expect(page.getByRole('dialog', { name: 'Choose a language' })).toBeVisible()
    },
  },
  {
    id: 'naming-editor',
    area: 'tracks',
    region: '[data-card="output"]',
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Summary')
      const output = page.locator('[data-card="output"]')
      await expect(output.getByTestId('naming-result')).toBeVisible()
      const parsed = output.getByRole('button', { name: 'Parsed name' })
      if ((await parsed.getAttribute('aria-expanded')) !== 'true') await parsed.click()
      await expect(parsed).toHaveAttribute('aria-expanded', 'true')
    },
  },
  {
    id: 'range',
    area: 'tracks',
    region: '.range-popover',
    async setup(page) {
      await openApp(page)
      await openFile(page, 'chapters.mkv', 'output')
      await page.locator('.workspace__header [data-field="range"]').click()
      const popover = page.locator('.range-popover')
      await expect(popover).toBeVisible()
      await popover.getByRole('radio', { name: 'Chapters', exact: true }).check()
    },
  },
  {
    id: 'group',
    area: 'tracks',
    region: '.group-banner',
    async setup(page) {
      await editSeason(page)
      await page
        .locator('.group-banner [data-field="scope"]')
        .getByRole('button', { name: /^This file only/ })
        .click()
    },
  },
  {
    id: 'matrix',
    area: 'tracks',
    region: '.matrix-dialog',
    async setup(page) {
      await seasonWithError(page)
      await page.locator('.group-banner [data-action="check-group"]').click()
      await expect(page.locator('.matrix-dialog tbody tr')).toHaveCount(12)
    },
  },
  {
    id: 'queue-group',
    area: 'tracks',
    region: '.queue-group-dialog',
    async setup(page) {
      await seasonWithError(page)
      await page.locator('.group-banner [data-action="queue-group"]').click()
      await expect(page.locator('.queue-group-dialog')).toBeVisible()
    },
  },
  {
    id: 'defaults',
    area: 'tracks',
    region: '.defaults-dialog',
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Audio')
      await page.locator('[data-action="defaults"]').click()
      await expect(page.locator('.defaults-dialog')).toBeVisible()
    },
  },
  {
    id: 'apply-to-group',
    area: 'tracks',
    region: DIALOG,
    async setup(page) {
      await openSeason(page)
      await page.getByRole('tree').locator('[aria-level="2"]').first().click()
      await page.locator('.group-banner [data-action="apply-to-group"]').click()
      await expect(page.locator(DIALOG)).toBeVisible()
    },
  },
]
