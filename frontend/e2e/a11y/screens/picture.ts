import type { Page } from '@playwright/test'

import { expect } from '../../support/test'
import { openAdvanced, openTab } from '../steps'
import type { Screen } from '../types'

const PANEL = (tab: string) => `[data-panel="${tab}"]`
const PREVIEW = '.preview-panel'

/** multitrack.mkv open, its frames in the preview panel. */
async function framesShown(page: Page): Promise<void> {
  await openTab(page, 'multitrack.mkv', 'Summary')
  await expect(page.locator(`${PREVIEW} [data-field="thumb"]`).first()).toBeVisible()
  await expect(page.locator(`${PREVIEW} img[data-field="frame"]`)).toBeVisible()
}

async function viewMode(page: Page, mode: string): Promise<void> {
  await page
    .locator(`${PREVIEW} [data-field="view-mode"]`)
    .getByRole('button', { name: mode, exact: true })
    .click()
}

export const screens: Screen[] = [
  {
    id: 'summary',
    area: 'picture',
    region: PANEL('summary'),
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Summary')
      await expect(page.locator('[data-card="source"]')).toBeVisible()
    },
  },
  {
    id: 'dimensions',
    area: 'picture',
    region: PANEL('dimensions'),
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Dimensions')
    },
  },
  {
    id: 'crop-manual',
    area: 'picture',
    // The handles are on the preview's frame, the magnifier in the tab.
    async setup(page) {
      await openTab(page, 'letterbox.mkv', 'Dimensions')
      await expect(page.locator('[data-line="detection"]')).toContainText('Detected')
      await page
        .locator('[data-control="crop-mode"]')
        .getByRole('button', { name: 'Manual', exact: true })
        .click()
      await expect(page.locator('[data-crop-magnifier] canvas').first()).toBeVisible()
    },
  },
  {
    id: 'filters',
    area: 'picture',
    region: PANEL('filters'),
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Filters')
    },
  },
  {
    id: 'video',
    area: 'picture',
    region: PANEL('video'),
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Video')
    },
  },
  {
    id: 'video-advanced',
    area: 'picture',
    region: '[data-section="advanced"]',
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Video')
      await openAdvanced(page)
    },
  },
  {
    id: 'command-drawer',
    area: 'picture',
    region: '.command-preview',
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Video')
      await page.getByRole('button', { name: 'FFmpeg command' }).click()
      await expect(page.getByLabel('The FFmpeg command of this job')).toContainText('ffmpeg')
    },
  },
  {
    id: 'preview-frames',
    area: 'picture',
    region: PREVIEW,
    setup: framesShown,
  },
  {
    id: 'split-compare',
    area: 'picture',
    region: PREVIEW,
    async setup(page) {
      await framesShown(page)
      await viewMode(page, 'Split')
      await expect(page.locator(`${PREVIEW} .split-compare`)).toBeVisible()
    },
  },
  {
    id: 'preview-clip',
    area: 'picture',
    region: PREVIEW,
    async setup(page) {
      await framesShown(page)
      await page.locator('[data-action="encode-clip"]').click()
      await expect(page.locator('[data-field="clip-result"]')).toBeVisible({ timeout: 60_000 })
    },
  },
]
