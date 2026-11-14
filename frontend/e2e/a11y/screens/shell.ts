import type { Page } from '@playwright/test'

import { openApp, openFile } from '../../support/app'
import { expect } from '../../support/test'
import { choosePreset, goTo, openTab } from '../steps'
import type { Screen } from '../types'

// Its encoder is unavailable under the fake FFmpeg, so the job has errors with fixes.
const UNAVAILABLE_PRESET = 'h265-nvenc-1080p'
const QUICK_PRESET = 'h264-mkv-1080p'
// The settings sections of the web app; the desktop section is the desktop app's only.
const SETTINGS_SECTIONS = [
  'tools',
  'encoders',
  'output',
  'languages',
  'preview',
  'queue',
  'appearance',
] as const

async function addToQueue(page: Page, toast = 'Added to the queue'): Promise<void> {
  const add = page.locator('.status-bar__add')
  await expect(add).toBeEnabled()
  await add.click()
  await expect(page.locator('.p-toast-message').filter({ hasText: toast })).not.toHaveCount(0)
}

/**
 * The queue with a done, a failed and a waiting job of multitrack.mkv. The failed one is
 * refused when it is added: a waiting job writes the same output.
 */
async function queueOfThree(page: Page): Promise<void> {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await choosePreset(page, QUICK_PRESET)
  await addToQueue(page)
  await addToQueue(page, 'The job was added as failed')
  await goTo(page, 'Queue')
  const view = page.locator('main[data-view="queue"]')
  const jobs = view.locator('[data-job]')
  await expect(jobs).toHaveCount(2)
  await view.getByRole('button', { name: 'Start', exact: true }).click()
  await expect(view.locator('[data-job][data-state="done"]')).toHaveCount(1, { timeout: 60_000 })
  await view.getByRole('button', { name: 'Stop', exact: true }).click()
  await goTo(page, 'Workspace')
  await addToQueue(page)
  await goTo(page, 'Queue')
  await expect(jobs).toHaveCount(3)
  await Promise.all(
    ['waiting', 'done', 'failed'].map((state) =>
      expect(view.locator(`[data-job][data-state="${state}"]`)).toHaveCount(1),
    ),
  )
}

export const screens: Screen[] = [
  {
    id: 'workspace-empty',
    area: 'shell',
    setup: openApp,
  },
  {
    id: 'file-browser',
    area: 'shell',
    region: '.file-browser-dialog',
    async setup(page) {
      await openApp(page)
      await page.keyboard.press('ControlOrMeta+O')
      await expect(page.locator('.file-browser-dialog')).toBeVisible()
      await expect(page.locator('.file-browser__entry').first()).toBeVisible()
    },
  },
  {
    id: 'preset-picker',
    area: 'shell',
    region: '.preset-picker__popover',
    async setup(page) {
      await openApp(page)
      await openFile(page, 'multitrack.mkv')
      await page.locator('.preset-picker__trigger').click()
      await expect(page.locator('.preset-picker__list')).toBeVisible()
    },
  },
  {
    id: 'status-issues',
    area: 'shell',
    region: '.validation-summary__list',
    async setup(page) {
      await openApp(page)
      await openFile(page, 'multitrack.mkv')
      await choosePreset(page, UNAVAILABLE_PRESET)
      await page.locator('.validation-summary').click()
      await expect(page.locator('.validation-summary__list .rf-issue').first()).toBeVisible()
    },
  },
  {
    // The whole workspace with a file open; a short tab, since each tab is a screen of its own.
    id: 'toast',
    area: 'shell',
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Tags')
      await addToQueue(page)
      // The pointer on the toast keeps it on screen for the checks.
      await page.locator('.p-toast-message').hover()
    },
  },
  {
    id: 'queue',
    area: 'shell',
    setup: queueOfThree,
  },
  {
    id: 'job-log',
    area: 'shell',
    region: '[data-component="job-log"]',
    async setup(page) {
      await queueOfThree(page)
      await page.locator('[data-job][data-state="failed"] [data-action="log"]').click()
      await expect(page.locator('[data-component="job-log"]')).toBeVisible()
    },
  },
  {
    id: 'activity',
    area: 'shell',
    async setup(page) {
      await openApp(page)
      await openFile(page, 'multitrack.mkv')
      await goTo(page, 'Activity')
      await expect(page.locator('main[data-view="activity"]')).toBeVisible()
    },
  },
  {
    id: 'presets',
    area: 'shell',
    async setup(page) {
      await openApp(page)
      await goTo(page, 'Presets')
      await expect(page.locator('.p-tree, [role="tree"]').first()).toBeVisible()
    },
  },
  {
    id: 'preset-name-dialog',
    area: 'shell',
    region: '.preset-name-dialog',
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Summary')
      await page.getByRole('button', { name: 'Preset actions', exact: true }).click()
      await page.getByRole('menuitem', { name: 'Save as new preset…' }).click()
      await expect(page.locator('.preset-name-dialog')).toBeVisible()
    },
  },
  {
    // The status bar and the editor in the error state, the whole page walked.
    id: 'status-error',
    area: 'shell',
    async setup(page) {
      await openTab(page, 'multitrack.mkv', 'Tags')
      await choosePreset(page, UNAVAILABLE_PRESET)
      await expect(page.locator('.validation-summary__part--error')).toBeVisible()
    },
  },
  {
    // The settings page with its navigation, every section walked in one go.
    id: 'settings',
    area: 'shell',
    async setup(page) {
      await openApp(page)
      await goTo(page, 'Settings')
      await expect(page.locator('[data-section-link="tools"]')).toBeVisible()
    },
  },
  ...SETTINGS_SECTIONS.map((section): Screen => ({
    id: `settings-${section}`,
    area: 'shell',
    region: `[data-section="${section}"]`,
    async setup(page) {
      await openApp(page)
      await goTo(page, 'Settings')
      await page.locator(`[data-section-link="${section}"]`).click()
      await expect(page.locator(`[data-section="${section}"]`)).toBeInViewport()
    },
  })),
  {
    id: 'login',
    area: 'shell',
    async setup(page) {
      await page.goto('/')
      await expect(page.locator('.login-screen')).toBeVisible()
    },
  },
]
