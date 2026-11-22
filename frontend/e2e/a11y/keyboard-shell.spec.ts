import type { Page } from '@playwright/test'

import { openApp, openFile } from '../support/app'
import { expect, test } from '../support/test'
import { openSeason } from './steps'

// The keyboard paths of the shell that only a browser shows: the real Tab order and focus.

interface Focused {
  matches(selector: string): boolean
  blur(): void
}

// This file is type-checked without the DOM library.
function focusedMatches(page: Page, selector: string): Promise<boolean> {
  return page.evaluate((wanted) => {
    const doc = Reflect.get(globalThis, 'document') as { activeElement: Focused | null }
    return doc.activeElement?.matches(wanted) ?? false
  }, selector)
}

test('opens a file with Ctrl+O and the keys alone, and the focus lands in the workspace', async ({
  page,
}) => {
  await openApp(page)
  // As after a page load: the focus on no control, so the dialog has none to give back.
  await page.evaluate(() => {
    const doc = Reflect.get(globalThis, 'document') as { activeElement: Focused | null }
    doc.activeElement?.blur()
  })
  await page.keyboard.press('ControlOrMeta+O')
  const dialog = page.locator('.file-browser-dialog')
  await expect(dialog).toBeVisible()
  const list = dialog.locator('[role="listbox"]')
  await expect(list).toBeFocused()
  const file = dialog.locator('.file-browser__entry[data-name="multitrack.mkv"]')
  await expect(file).toBeVisible()
  // Type-ahead to the file, and Enter opens the file under the cursor.
  await page.keyboard.type('mu')
  await expect(list).toHaveAttribute('aria-activedescendant', (await file.getAttribute('id'))!)
  await page.keyboard.press('Enter')
  await expect(dialog).toBeHidden()
  await expect
    .poll(() =>
      focusedMatches(page, '.editor-tabs [role="tab"][aria-selected="true"], .workspace__open'),
    )
    .toBe(true)
  await expect(page.locator('.preset-picker__trigger')).toBeEnabled()
})

test('edits a group from the sources panel with the keyboard', async ({ page }) => {
  await openSeason(page)
  const group = page.getByRole('tree').locator('[aria-level="1"]')
  await group.focus()
  await page.keyboard.press('Shift+F10')
  // The menu takes the focus, on its first item.
  const menu = page.locator('[data-menu="sources"] [role="menubar"]')
  await expect(menu).toBeFocused()
  await expect(menu).toHaveAttribute(
    'aria-activedescendant',
    (await menu.getByRole('menuitem', { name: 'Edit group' }).getAttribute('id'))!,
  )
  await page.keyboard.press('Enter')
  await expect(page.locator('.group-banner')).toBeVisible()
  await expect(group).toHaveAttribute('aria-current', 'true')
  await expect(group).toHaveAttribute('aria-expanded', 'true')
})

test('goes between the preset filter and the list with Tab both ways, and Escape returns', async ({
  page,
}) => {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  const trigger = page.locator('.preset-picker__trigger')
  await trigger.focus()
  await page.keyboard.press('Enter')
  const filter = page.locator('.preset-picker__list .p-listbox-filter')
  await expect(filter).toBeFocused()
  await page.keyboard.press('Tab')
  const list = page.locator('.preset-picker__list [role="listbox"]')
  await expect(list).toBeFocused()
  // The list shows where the focus is: the job's preset.
  await expect(list).toHaveAttribute('aria-activedescendant', /.+/)
  await expect(page.locator('.preset-picker__list .p-listbox-option.p-focus')).toHaveText(
    /H\.265 MKV 1080p/,
  )
  await page.keyboard.press('Tab')
  await expect(filter).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(list).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(filter).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(trigger).toBeFocused()
})
