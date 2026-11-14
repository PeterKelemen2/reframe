import type { Page } from '@playwright/test'

import { openApp, openFile } from './support/app'
import { expect, test } from './support/test'

// letterbox.mkv: 320×180, 2 s of 2.39:1 letterbox (bars of 22 and 24 rows), then 2 s of 4:3.
const SOURCE = { width: 320, height: 180 }
// The crop the flow sets: top and left typed off the 4:2:0 grid, right moved with the keys.
const CROP = { top: 22, bottom: 24, left: 16, right: 18 }

// The magnifier's tint and crop line (CropMagnifier): magenta at 35 % and solid yellow.
const TINT = [255, 0, 90]
const TINT_ALPHA = 0.35
const LINE = [255, 212, 0]
// Compositing the tint rounds differently per browser.
const TOLERANCE = 3

type Edge = keyof typeof CROP

interface Pixels {
  width: number
  height: number
  data: number[]
  /** A canvas's content box in CSS pixels, and the device pixel ratio. */
  box: { width: number; height: number; ratio: number }
}

/** A canvas's pixels (`selector`), or the decoded PNG of an image's `src`. */
function pixels(page: Page, selector: string): Promise<Pixels> {
  return page.evaluate(async (wanted) => {
    // This file is type-checked without the DOM library.
    interface Context {
      drawImage(image: unknown, x: number, y: number): void
      getImageData(x: number, y: number, w: number, h: number): { data: ArrayLike<number> }
    }
    interface Element {
      width: number
      height: number
      clientWidth: number
      clientHeight: number
      src?: string
      getContext(kind: '2d'): Context
    }
    const doc = Reflect.get(globalThis, 'document') as { querySelector(s: string): Element | null }
    const element = doc.querySelector(wanted)
    if (element === null) throw new Error(`${wanted} is not on the page`)
    let canvas = element
    if (element.src !== undefined) {
      // Decoded as the magnifier decodes it, without a colour space conversion.
      const blob = await (await fetch(element.src)).blob()
      const decode = Reflect.get(globalThis, 'createImageBitmap') as (
        blob: Blob,
        options: object,
      ) => Promise<{ width: number; height: number }>
      const bitmap = await decode(blob, { colorSpaceConversion: 'none' })
      const Offscreen = Reflect.get(globalThis, 'OffscreenCanvas') as new (
        w: number,
        h: number,
      ) => Element
      canvas = new Offscreen(bitmap.width, bitmap.height)
      canvas.getContext('2d').drawImage(bitmap, 0, 0)
    }
    const { data } = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height)
    const box = {
      width: element.clientWidth,
      height: element.clientHeight,
      ratio: Reflect.get(globalThis, 'devicePixelRatio') as number,
    }
    return { width: canvas.width, height: canvas.height, data: Array.from(data), box }
  }, selector)
}

type Kind = 'kept' | 'tinted' | 'line' | 'other'
const KINDS = ['kept', 'tinted', 'line'] as const

/** Whether the shown pixel at `at` is `kind` of the source pixel at `from`. */
function shows(kind: Kind, shown: Pixels, at: number, source: Pixels, from: number): boolean {
  for (let channel = 0; channel < 3; channel += 1) {
    const value = source.data[from + channel] ?? 0
    const expected =
      kind === 'kept'
        ? value
        : kind === 'tinted'
          ? value * (1 - TINT_ALPHA) + (TINT[channel] ?? 0) * TINT_ALPHA
          : (LINE[channel] ?? 0)
    if (Math.abs((shown.data[at + channel] ?? -99) - expected) > TOLERANCE) return false
  }
  return true
}

const horizontal = (edge: Edge) => edge === 'top' || edge === 'bottom'

/**
 * What each line of a strip across its crop line shows (canvas rows of the top and bottom
 * strips, columns of the left and right ones), as runs: `tinted×47 line×2 kept×47`. A line is
 * `kept` or `tinted` when every pixel on it is the source frame's (tinted) pixel at `zoom`, from
 * the source row or column `first` on. The canvas has `devicePixelRatio` pixels per CSS pixel.
 */
function strip(shown: Pixels, source: Pixels, edge: Edge, zoom: number, first: number): string {
  // The page scales a canvas whose pixels are not its box at the device pixel ratio, and that
  // smooths the zoomed pixels and the line.
  const { box } = shown
  if (shown.width !== box.width * box.ratio || shown.height !== box.height * box.ratio) {
    return `${shown.width}×${shown.height} canvas in a ${box.width}×${box.height} box at ×${box.ratio}`
  }
  const scale = zoom * box.ratio
  const across = horizontal(edge) ? shown.height : shown.width
  const along = horizontal(edge) ? shown.width : shown.height
  const extent = horizontal(edge) ? source.width : source.height
  const offset = (image: Pixels, line: number, pixel: number) =>
    (horizontal(edge) ? line * image.width + pixel : pixel * image.width + line) * 4
  const kinds = (start: number): Kind[] =>
    Array.from(
      { length: across },
      (_, line) =>
        KINDS.find((kind) => {
          for (let pixel = 0; pixel < along; pixel += 1) {
            const from = offset(
              source,
              first + Math.floor(line / scale),
              start + Math.floor(pixel / scale),
            )
            if (!shows(kind, shown, offset(shown, line, pixel), source, from)) return false
          }
          return true
        }) ?? 'other',
    )
  // Along its crop line the strip follows the pointer: find where it starts.
  const known = (list: Kind[]) => list.filter((kind) => kind !== 'other').length
  let best: Kind[] = []
  for (let start = 0; start + along / scale <= extent; start += 1) {
    const found = kinds(start)
    if (known(found) > known(best)) best = found
  }
  return runs(best)
}

/**
 * The strip that shows the crop at `boundary` (the first kept or the first removed line), `depth`
 * CSS pixels deep at `ratio` canvas pixels per CSS pixel.
 */
function expectedStrip(
  edge: Edge,
  zoom: number,
  first: number,
  boundary: number,
  depth: number,
  ratio: number,
): string {
  const removedFirst = edge === 'top' || edge === 'left'
  const scale = zoom * ratio
  const at = (boundary - first) * scale
  const kinds = Array.from({ length: depth * ratio }, (_, line): Kind => {
    // Two CSS pixels wide, one on each side of the boundary.
    if (line >= at - ratio && line < at + ratio) return 'line'
    const before = first + Math.floor(line / scale) < boundary
    return before === removedFirst ? 'tinted' : 'kept'
  })
  return runs(kinds)
}

function runs(kinds: Kind[]): string {
  const parts: [Kind, number][] = []
  for (const kind of kinds) {
    const last = parts.at(-1)
    if (last?.[0] === kind) last[1] += 1
    else parts.push([kind, 1])
  }
  return parts.map(([kind, count]) => `${kind}×${count}`).join(' ')
}

/** The source row or column where the crop line of `edge` is, from the crop the inputs show. */
function boundaryOf(edge: Edge, crop: Record<Edge, number>): number {
  switch (edge) {
    case 'top':
      return crop.top
    case 'bottom':
      return SOURCE.height - crop.bottom
    case 'left':
      return crop.left
    case 'right':
      return SOURCE.width - crop.right
  }
}

const EDGES: Edge[] = ['top', 'bottom', 'left', 'right']

/** Each edge strip of the magnifier at `zoom` shows the tint and the crop line at `crop`. */
async function expectStrips(page: Page, zoom: number, crop: Record<Edge, number>): Promise<void> {
  const magnifier = page.locator('[data-crop-magnifier]')
  await expect(magnifier.locator('[data-field="magnifier-zoom"] [aria-pressed="true"]')).toHaveText(
    `${zoom}×`,
  )
  const source = await pixels(page, 'img[data-field="frame"]')
  await Promise.all(
    EDGES.map(async (edge) => {
      const figure = magnifier.locator(`[data-edge="${edge}"]`)
      const range = await figure.locator('[data-range]').textContent()
      const first = Number(/(\d+)–/.exec(range ?? '')?.[1])
      const selector = `[data-crop-magnifier] [data-edge="${edge}"] canvas`
      const { box } = await pixels(page, selector)
      const depth = horizontal(edge) ? box.height : box.width
      const shown = () =>
        pixels(page, selector).then((canvas) => strip(canvas, source, edge, zoom, first))
      await expect
        .poll(shown, { message: `${edge} strip at ${zoom}× (${range})` })
        .toBe(expectedStrip(edge, zoom, first, boundaryOf(edge, crop), depth, box.ratio))
    }),
  )
}

test('a manual crop: the magnifier shows its lines, the command has its crop filter', async ({
  page,
}) => {
  await openApp(page)
  await openFile(page, 'letterbox.mkv')

  await page.getByRole('tab', { name: 'Dimensions' }).click()
  await expect(page.locator('[data-line="detection"]')).toHaveText(
    'Detected 22 / 24 / 0 / 0 on 5 of 10 frames',
  )
  await page
    .locator('[data-control="crop-mode"]')
    .getByRole('button', { name: 'Manual', exact: true })
    .click()

  const input = (edge: Edge) => page.locator(`input[data-edge="${edge}"]`)
  const note = page.locator('[data-note="snap"]')
  const type = async (edge: Edge, value: string) => {
    await input(edge).fill(value)
    await input(edge).blur()
  }
  await type('top', '23')
  await expect(note).toHaveText('Top 23 → 22 (4:2:0 chroma grid)')
  await expect(input('top')).toHaveValue('22')
  await type('bottom', '24')
  await type('left', '17')
  await expect(note).toHaveText('Left 17 → 16 (4:2:0 chroma grid)')
  await expect(input('left')).toHaveValue('16')

  // The right edge moves in by 8 chroma steps, then one more.
  const handle = page.locator('[data-crop-handle="right"]')
  await handle.press('Shift+ArrowLeft')
  await handle.press('ArrowLeft')
  await expect(handle).toHaveAttribute('aria-valuenow', String(CROP.right))
  // The arrows moved the edge, not the panel's frame.
  await expect(page.locator('[data-crop-magnifier] [data-frame-label]')).toHaveText('Frame 1 / 10')

  const shown = Object.fromEntries(
    await Promise.all(EDGES.map(async (edge) => [edge, Number(await input(edge).inputValue())])),
  ) as Record<Edge, number>
  expect(shown).toEqual(CROP)

  await expectStrips(page, 4, shown)
  await page
    .locator('[data-crop-magnifier] [data-field="magnifier-zoom"]')
    .getByRole('button', { name: '8×' })
    .click()
  await expectStrips(page, 8, shown)

  await page.getByRole('tab', { name: 'Video' }).click()
  await page.getByRole('button', { name: 'FFmpeg command' }).click()
  const command = page.getByLabel('The FFmpeg command of this job')
  const crops = async () => (await command.textContent())?.match(/crop=[\d:]+/g) ?? []
  const width = SOURCE.width - shown.left - shown.right
  const height = SOURCE.height - shown.top - shown.bottom
  await expect.poll(crops).toEqual([`crop=${width}:${height}:${shown.left}:${shown.top}`])
})
