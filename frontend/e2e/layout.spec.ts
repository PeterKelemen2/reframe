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

type Rgb = [number, number, number]

type Rgba = [number, number, number, number]

function rgba(css: string): Rgba {
  const [r = 0, g = 0, b = 0, a = 1] = (/\(([^)]+)\)/.exec(css)?.[1] ?? '')
    .split(/[\s,/]+/)
    .map(Number)
  return [r, g, b, a]
}

function over([r, g, b, a]: Rgba, under: Rgb): Rgb {
  return [r * a + under[0] * (1 - a), g * a + under[1] * (1 - a), b * a + under[2] * (1 - a)]
}

/** The colour of the element's fill as painted: its background, faded by its opacity, on what lies under it. */
async function paintedFill(page: Page, selector: string): Promise<Rgb> {
  const painted = await page.evaluate((wanted) => {
    // This file is type-checked without the DOM library.
    interface Box {
      parentElement: Box | null
    }
    const doc = Reflect.get(globalThis, 'document') as { querySelector(s: string): Box | null }
    const style = Reflect.get(globalThis, 'getComputedStyle') as (box: Box) => {
      backgroundColor: string
      opacity: string
    }
    const element = doc.querySelector(wanted)
    if (element === null) throw new Error(`${wanted} is not on the page`)
    const parents: string[] = []
    for (let box = element.parentElement; box !== null; box = box.parentElement) {
      parents.push(style(box).backgroundColor)
    }
    let opacity = 1
    for (let box: Box | null = element; box !== null; box = box.parentElement) {
      opacity *= Number(style(box).opacity)
    }
    return { fill: style(element).backgroundColor, opacity, parents }
  }, selector)
  // What lies under it: its parents' backgrounds, from the first opaque one up.
  const layers = painted.parents.map(rgba)
  const opaque = layers.findIndex((layer) => layer[3] >= 1)
  let under: Rgb = [255, 255, 255]
  for (const layer of layers.slice(0, opaque === -1 ? undefined : opaque + 1).toReversed()) {
    under = over(layer, under)
  }
  const [r, g, b, a] = rgba(painted.fill)
  return over([r, g, b, a * painted.opacity], under)
}

function contrast(one: Rgb, other: Rgb): number {
  const luminance = (rgb: Rgb): number => {
    const [r = 0, g = 0, b = 0] = rgb.map((channel) => {
      const c = channel / 255
      return c <= 0.040_45 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const [x, y] = [luminance(one), luminance(other)]
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
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

test("the open command drawer covers the padding where a field's bar is drawn", async ({
  page,
}) => {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await page.getByRole('tab', { name: 'Video' }).click()

  const drawer = page.locator('.command-preview')
  const toggle = drawer.locator('.command-preview__toggle')
  await expect(toggle).toBeVisible()
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click()
  await expect(drawer.locator('.command-preview__body')).toBeVisible()

  const box = await drawer.boundingBox()
  if (box === null) throw new Error('the drawer has no box')
  // A field's bar is drawn 8 px left of the field, 3 px wide: its middle is 6 px left of the drawer.
  const hit = await page.evaluate(
    ({ x, y }) => {
      // This file is type-checked without the DOM library.
      interface Box {
        closest(selector: string): Box | null
      }
      const doc = Reflect.get(globalThis, 'document') as {
        elementFromPoint(x: number, y: number): Box | null
      }
      return doc.elementFromPoint(x, y)?.closest('.command-preview') != null
    },
    { x: box.x - 6, y: box.y + box.height / 2 },
  )
  expect(hit, 'the drawer is what is painted beside its own left edge').toBe(true)
})

/** The distance between the bottom edges of the editor's panels and of the command drawer. */
async function gapUnderDrawer(page: Page): Promise<number> {
  const panels = await page.locator('.editor-tabs__panels').boundingBox()
  const drawer = await page.locator('.command-preview').boundingBox()
  if (panels === null || drawer === null) return Number.NaN
  return Math.abs(panels.y + panels.height - (drawer.y + drawer.height))
}

async function scrollPanelsTo(page: Page, where: 'top' | 'end'): Promise<void> {
  await page.evaluate((to) => {
    // This file is type-checked without the DOM library.
    interface Panels {
      scrollTop: number
      scrollHeight: number
    }
    const doc = Reflect.get(globalThis, 'document') as {
      querySelector(selector: string): Panels | null
    }
    const panels = doc.querySelector('.editor-tabs__panels')
    if (panels !== null) panels.scrollTop = to === 'end' ? panels.scrollHeight : 0
  }, where)
}

async function expectDrawerFlush(page: Page, state: string): Promise<void> {
  // A gap under the drawer shows whatever scrolls beneath it.
  await scrollPanelsTo(page, 'top')
  await expect.poll(() => gapUnderDrawer(page), `${state}, at the top`).toBeLessThanOrEqual(1)
  await scrollPanelsTo(page, 'end')
  await expect.poll(() => gapUnderDrawer(page), `${state}, at the end`).toBeLessThanOrEqual(1)
}

test("the command drawer ends at the panel's bottom edge, closed and open", async ({ page }) => {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await page.getByRole('tab', { name: 'Video' }).click()

  const toggle = page.locator('.command-preview__toggle')
  await expect(toggle).toBeVisible()
  if ((await toggle.getAttribute('aria-expanded')) === 'true') await toggle.click()
  await expectDrawerFlush(page, 'closed')
  await toggle.click()
  await expect(page.locator('.command-preview__body')).toBeVisible()
  await expectDrawerFlush(page, 'open')
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

test('a disabled Add to queue does not look like an enabled button, in light and dark', async ({
  page,
}) => {
  await openApp(page)
  await openFile(page, 'multitrack.mkv')
  await page.locator('.preset-picker__trigger').click()
  await page.locator(`.preset-picker__list [data-preset="${UNAVAILABLE_PRESET}"]`).click()
  await expect(page.locator('.status-bar__add')).toBeDisabled()
  await expect(page.locator('[data-action="open-files"]')).toBeEnabled()

  const fills = async (): Promise<number> =>
    contrast(
      await paintedFill(page, '.status-bar__add'),
      await paintedFill(page, '[data-action="open-files"]'),
    )
  // Colours change with a short transition: measure once they have settled.
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
  await expect(page.locator('html')).not.toHaveClass(/reframe-dark/)
  await expect
    .poll(fills, { message: 'light: the disabled fill against the enabled one' })
    .toBeGreaterThanOrEqual(3)
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await expect(page.locator('html')).toHaveClass(/reframe-dark/)
  await expect
    .poll(fills, { message: 'dark: the disabled fill against the enabled one' })
    .toBeGreaterThanOrEqual(3)
})
