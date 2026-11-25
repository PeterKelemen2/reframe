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

/**
 * How much of a Video option is painted where the command drawer is: the part of each field
 * that its scroller shows, cut by the drawer's box. 0 when the drawer covers no option.
 */
function optionsUnderDrawer(page: Page): Promise<number> {
  return page.evaluate(() => {
    // This file is type-checked without the DOM library.
    interface Rect {
      top: number
      bottom: number
    }
    interface Box {
      getBoundingClientRect(): Rect
      parentElement: Box | null
    }
    const doc = Reflect.get(globalThis, 'document') as {
      querySelector(selector: string): Box | null
      querySelectorAll(selector: string): Iterable<Box>
    }
    const view = Reflect.get(globalThis, 'getComputedStyle') as (box: Box) => { overflowY: string }
    const drawer = doc.querySelector('.command-preview')?.getBoundingClientRect()
    if (drawer === undefined) return Number.NaN
    let worst = 0
    for (const field of doc.querySelectorAll('[data-tab="video"] .rf-field')) {
      let shown = field.getBoundingClientRect()
      for (let box = field.parentElement; box !== null; box = box.parentElement) {
        if (!['auto', 'scroll', 'hidden', 'clip'].includes(view(box).overflowY)) continue
        const clip = box.getBoundingClientRect()
        shown = { top: Math.max(shown.top, clip.top), bottom: Math.min(shown.bottom, clip.bottom) }
      }
      const under = Math.min(shown.bottom, drawer.bottom) - Math.max(shown.top, drawer.top)
      worst = Math.max(worst, under)
    }
    return worst
  })
}

async function scrollOptionsTo(page: Page, where: 'top' | 'end'): Promise<void> {
  await page.evaluate((to) => {
    // This file is type-checked without the DOM library.
    interface Scroller {
      scrollTop: number
      scrollHeight: number
    }
    const doc = Reflect.get(globalThis, 'document') as {
      querySelectorAll(selector: string): Iterable<Scroller>
    }
    for (const box of doc.querySelectorAll('.editor-tabs__panels, .video-tab__content')) {
      box.scrollTop = to === 'end' ? box.scrollHeight : 0
    }
  }, where)
}

test('the open command drawer covers no Video option, the options scrolled to the top or the end', async ({
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

  // An option under the drawer cannot be reached by the pointer and keeps a smaller target.
  await scrollOptionsTo(page, 'top')
  await expect.poll(() => optionsUnderDrawer(page), 'scrolled to the top').toBeLessThan(0.5)
  await scrollOptionsTo(page, 'end')
  await expect.poll(() => optionsUnderDrawer(page), 'scrolled to the end').toBeLessThan(0.5)
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

  // An enabled primary button's fill: the add is the status bar's only one.
  await page.evaluate(() => {
    interface Box {
      id: string
      style: { background: string; width: string; height: string }
      append(child: Box): void
    }
    const doc = Reflect.get(globalThis, 'document') as {
      createElement(tag: string): Box
      querySelector(s: string): Box
    }
    const probe = doc.createElement('span')
    probe.id = 'primary-fill'
    probe.style.background = 'var(--p-button-primary-background)'
    probe.style.width = '1px'
    probe.style.height = '1px'
    doc.querySelector('.status-bar__actions').append(probe)
  })
  const fills = async (): Promise<number> =>
    contrast(await paintedFill(page, '.status-bar__add'), await paintedFill(page, '#primary-fill'))
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
