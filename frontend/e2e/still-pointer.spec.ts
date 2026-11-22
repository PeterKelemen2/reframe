import type { Locator, Page } from '@playwright/test'

import { openTab } from './a11y/steps'
import { expect, test } from './support/test'

// WebKit sends a mousemove at the pointer's place when the content under a still pointer
// changes: a list opens, scrolls or filters. A list whose active option follows the pointer
// must not take it from the arrow keys then. The pauses are a person's: WebKit sends that move
// on a timer, and only after the keys stop for a moment.

/** Presses `key` `times` times, `pause` ms apart. */
async function press(page: Page, key: string, times: number, pause: number): Promise<void> {
  for (let i = 0; i < times; i += 1) {
    // oxlint-disable-next-line eslint/no-await-in-loop -- a person's keys, one after the other
    await page.keyboard.press(key).then(() => page.waitForTimeout(pause))
  }
}

/** Moves the pointer onto `x, y` (two steps, the last of one pixel) and leaves it there. */
async function restAt(page: Page, x: number, y: number): Promise<void> {
  await page.mouse.move(x - 1, y)
  await page.mouse.move(x, y)
}

async function scrolls(list: Locator): Promise<boolean> {
  return list.evaluate((element) => element.scrollHeight > element.clientHeight)
}

test('a Select keeps the option of the arrow keys under a pointer that rests on its list', async ({
  page,
}) => {
  await openTab(page, 'multitrack.mkv', 'Video')
  const select = page.getByRole('combobox', { name: 'Frame rate', exact: true })
  await select.click()
  const list = page.locator('.p-select-list-container')
  await expect(list).toBeVisible()
  expect(await scrolls(list)).toBe(true)
  const options = page.getByRole('option')
  const labels = await options.allTextContents()
  const focused = page.locator('.p-select-option.p-focus')

  // The pointer goes to the third option and the list follows it; then it rests there.
  const third = (await options.nth(2).boundingBox())!
  await restAt(page, third.x + 20, third.y + third.height / 2)
  await expect(focused).toHaveText(labels[2]!)

  await press(page, 'ArrowDown', 10, 60)
  await page.waitForTimeout(500)
  await press(page, 'ArrowDown', 3, 300)
  await expect(focused).toHaveText(labels[15]!)
  await page.keyboard.press('Enter')
  await expect(list).toBeHidden()
  await expect(select).toHaveText(labels[15]!)
})

test('the language picker keeps the option of the keys under a pointer that rests beside its list', async ({
  page,
}) => {
  await openTab(page, 'multitrack.mkv', 'Audio')
  const block = page.locator('[data-metadata="audio[1].metadata"]')
  await block.locator('[data-action="metadata-toggle"]').click()
  const trigger = block.locator('.language-picker__trigger')
  await trigger.click()
  const search = page.getByRole('combobox', { name: 'Search languages' })
  await expect(search).toBeFocused()
  const active = async () => {
    const id = await search.getAttribute('aria-activedescendant')
    return id === null ? null : page.locator(`[id="${id}"]`).getAttribute('data-tag')
  }

  // A short list, and the pointer rests below it on the dialog.
  await page.keyboard.type('fren')
  await expect.poll(active).toBe('fr')
  const short = (await page.locator('.language-picker__list').boundingBox())!
  const at = { x: short.x + 60, y: short.y + short.height + 20 }
  await restAt(page, at.x, at.y)
  const optionAt = () =>
    page.evaluate(({ x, y }) => {
      // This file is type-checked without the DOM library.
      const doc = Reflect.get(globalThis, 'document') as {
        elementFromPoint(x: number, y: number): { closest(selector: string): unknown } | null
      }
      return doc.elementFromPoint(x, y)?.closest('[role="option"]') != null
    }, at)
  expect(await optionAt()).toBe(false)
  // The keys empty the search: the whole list is under the pointer now, and they move through it.
  await press(page, 'Backspace', 4, 50)
  await expect(search).toHaveValue('')
  expect(await scrolls(page.locator('.language-picker__list'))).toBe(true)
  expect(await optionAt()).toBe(true)
  await page.waitForTimeout(400)
  await press(page, 'ArrowDown', 12, 50)
  await page.waitForTimeout(300)
  const twelfth = await page.locator('.language-picker__option').nth(12).getAttribute('data-tag')
  await expect.poll(active).toBe(twelfth)
  await page.keyboard.press('Enter')
  await expect(trigger).toHaveAttribute('data-tag', twelfth!)
})
