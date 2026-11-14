/* oxlint-disable eslint/no-await-in-loop -- the checks, and the Tabs of a walk, take turns on one page */
import { AxeBuilder } from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

import { DARK_MODE_CLASS } from '../../src/styles/theme'
import { PROBE_GLOBAL, type ProbeApi, type ProbeFinding, type ShotPlace } from './probeApi'
import type { Browser, Check, Finding, Known, Screen, Theme } from './types'

// Loaded at run time and never followed by this program's type check: it needs the DOM library,
// which the end-to-end tests are checked without (tsconfig.e2e-page.json checks it).
const PROBE_MODULE = './page/probe'

/** axe's tags for the WCAG 2.0, 2.1 and 2.2 A and AA rules. */
export const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa']

/** Longer than the delay of PrimeVue's blur handlers (100 ms in Select). */
const SETTLE_MS = 200

/** More stops than any screen has: a walk that reaches it is cut and the screen needs a region. */
const WALK_LIMIT = 250

/** axe's reasons for leaving a text contrast open that the probe cannot measure either. */
const UNMEASURED = new Set(['bgImage', 'imgNode', 'equalRatio', 'colorParse'])
/** Text that axe takes for an icon: held to the 3:1 of a graphic. */
const ICON_TEXT = new Set(['shortTextContent', 'nonBmp'])

const OPPOSITE: Record<string, string> = {
  ArrowRight: 'ArrowLeft',
  ArrowLeft: 'ArrowRight',
  ArrowDown: 'ArrowUp',
  ArrowUp: 'ArrowDown',
}

async function call<K extends keyof ProbeApi>(
  page: Page,
  name: K,
  ...args: Parameters<ProbeApi[K]>
): Promise<Awaited<ReturnType<ProbeApi[K]>>> {
  const result: unknown = await page.evaluate(
    ({ global, name: wanted, args: given }) => {
      const probe = Reflect.get(globalThis, global) as Record<string, unknown> | undefined
      const fn = probe?.[wanted]
      if (typeof fn !== 'function') throw new Error('the gate probe is not installed')
      return (fn as (...a: unknown[]) => unknown)(...given)
    },
    { global: PROBE_GLOBAL, name, args },
  )
  return result as Awaited<ReturnType<ProbeApi[K]>>
}

/** Prepares a page for a screen: the probe, light, reduced motion. Before the first `goto`. */
export async function preparePage(page: Page): Promise<void> {
  const { installProbe } = (await import(PROBE_MODULE)) as { installProbe: () => void }
  await page.addInitScript(installProbe)
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
}

async function useTheme(page: Page, theme: Theme): Promise<void> {
  await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' })
  const html = page.locator('html')
  const dark = new RegExp(`\\b${DARK_MODE_CLASS}\\b`)
  if (theme === 'dark') await expect(html).toHaveClass(dark)
  else await expect(html).not.toHaveClass(dark)
  await call(page, 'settled')
}

function tag(
  screen: Screen,
  check: Check,
  theme: Theme,
  findings: readonly ProbeFinding[],
): Finding[] {
  return findings.map((finding) => ({ screen: screen.id, check, theme, ...finding }))
}

export async function motionFindings(page: Page, screen: Screen, theme: Theme): Promise<Finding[]> {
  return tag(screen, 'motion', theme, await call(page, 'motion'))
}

function selectorOf(target: readonly unknown[]): string {
  return target.map((part) => (Array.isArray(part) ? part.join(' ') : String(part))).join(' ')
}

function reasonOf(data: unknown): string {
  return typeof data === 'object' && data !== null && 'messageKey' in data
    ? String(data.messageKey)
    : 'unknown'
}

/**
 * axe on the whole page, whatever the screen's region: a region only narrows the focus walk. The
 * text contrasts axe leaves open (a gradient, a pseudo-element, an element partly covered) are
 * measured by the probe; what neither can measure is noted on the test.
 */
export async function axeFindings(page: Page, screen: Screen, theme: Theme): Promise<Finding[]> {
  const { violations, incomplete } = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze()
  const nodes = violations.flatMap((violation) =>
    violation.nodes.map((node) => ({
      rule: violation.id,
      selector: selectorOf(node.target),
      detail: node.failureSummary?.split('\n').slice(1).join(' ').trim(),
    })),
  )
  const unmeasured = new Map<string, number>()
  const count = (why: string) => unmeasured.set(why, (unmeasured.get(why) ?? 0) + 1)
  const open = incomplete
    .filter((result) => result.id === 'color-contrast')
    .flatMap((result) =>
      result.nodes.map((node) => ({
        selector: selectorOf(node.target),
        reason: reasonOf(node.any[0]?.data),
      })),
    )
    .filter((node) => {
      if (!UNMEASURED.has(node.reason)) return true
      count(node.reason)
      return false
    })
  const measured = await call(
    page,
    'measureText',
    open.map((node) => node.selector),
  )
  open.forEach((node, index) => {
    const result = measured[index]
    if (result === undefined) return
    if (result.skip !== undefined) {
      count(result.skip)
      return
    }
    const need = ICON_TEXT.has(node.reason) ? 3 : result.need
    if (result.ratio < need) {
      nodes.push({
        rule: 'color-contrast-measured',
        selector: node.selector,
        detail: `${result.ratio.toFixed(2)}:1, ${need}:1 needed (axe: ${node.reason})`,
      })
    }
  })
  if (unmeasured.size > 0) {
    test.info().annotations.push({
      type: 'contrast not measured',
      description: `${screen.id} ${theme}: ${[...unmeasured].map(([why, n]) => `${why} ${n}`).join(', ')}`,
    })
  }
  const targets = await call(
    page,
    'describeAll',
    nodes.map((node) => node.selector),
  )
  return tag(
    screen,
    'axe',
    theme,
    nodes.map((node, index) => ({
      rule: node.rule,
      target: targets[index] ?? node.selector,
      detail: node.detail,
    })),
  )
}

type Pictures = Partial<Record<Theme, { png: string; place: ShotPlace }>>

async function pictures(page: Page, shot: number): Promise<Pictures> {
  const taken: Pictures = {}
  for (const theme of ['light', 'dark'] as const) {
    await call(page, 'setTheme', theme)
    const place = await call(page, 'shotPlace', shot)
    if (place === null) continue
    const png = await page.screenshot({ clip: place.clip, scale: 'device', caret: 'hide' })
    taken[theme] = { png: png.toString('base64'), place }
  }
  await call(page, 'setTheme', null)
  return taken
}

/** Judges stops by their pictures, now that they have lost the focus. */
async function pixelFindings(
  page: Page,
  screen: Screen,
  shots: readonly number[],
  focused: Map<number, Pictures>,
): Promise<Finding[]> {
  const found: Finding[] = []
  for (const shot of shots) {
    if (!(await call(page, 'looksPlain', shot))) await page.waitForTimeout(SETTLE_MS)
    const before = focused.get(shot) ?? {}
    const after = await pictures(page, shot)
    for (const theme of ['light', 'dark'] as const) {
      const one = before[theme]
      const other = after[theme]
      if (one === undefined || other === undefined) continue
      const finding = await call(page, 'comparePixels', shot, one, other)
      if (finding !== null) found.push(...tag(screen, 'focus', theme, [finding]))
    }
  }
  return found
}

/** Resolves once the page has run a rendering update (layout, scroll, paint). */
async function renderingUpdate(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const frame = Reflect.get(globalThis, 'requestAnimationFrame') as (
          callback: () => void,
        ) => number
        frame(() => frame(() => resolve()))
      }),
  )
}

/** Moves the focus inside the stop's widget with an arrow key and back; judges the item met. */
async function arrowFindings(page: Page, screen: Screen, arrow: string): Promise<Finding[]> {
  let used = arrow
  await page.keyboard.press(used)
  let moved = await call(page, 'arrowSeen')
  if (!moved) {
    used = OPPOSITE[arrow] ?? arrow
    await page.keyboard.press(used)
    moved = await call(page, 'arrowSeen')
  }
  if (!moved) return []
  await page.keyboard.press(OPPOSITE[used] ?? used)
  const back = await call(page, 'arrowBack')
  return [...tag(screen, 'focus', 'light', back.light), ...tag(screen, 'focus', 'dark', back.dark)]
}

/**
 * Tabs through the screen and judges each stop in both themes once the focus has left it: its
 * focused paint against its unfocused paint (`probe.ts`), or its pictures where paint over a
 * picture or through a filter cannot be computed. A whole-page walk starts at the top of the
 * page, a region's at the top of the region. The item an arrow key reaches inside a stop's
 * widget is judged too.
 */
export async function focusFindings(page: Page, screen: Screen): Promise<Finding[]> {
  const found: Finding[] = []
  const region = screen.region ?? null
  const start = region ?? 'body'
  expect(await call(page, 'enterRegion', start), `the region ${start}`).toBe(true)
  // The set-up's focused element has just lost the focus: its blur settles before its look.
  await page.waitForTimeout(SETTLE_MS)
  await call(page, 'walkStart', DARK_MODE_CLASS, WALK_LIMIT, region)
  const focused = new Map<number, Pictures>()
  for (;;) {
    await page.keyboard.press('Tab')
    await call(page, 'leaveRegion', start)
    // WebKit scrolls the new stop into view at its next rendering update, not on the Tab.
    await renderingUpdate(page)
    let step = await call(page, 'walkStep')
    if (step.settle) {
      await page.waitForTimeout(SETTLE_MS)
      step = await call(page, 'walkStep')
    }
    found.push(...tag(screen, 'focus', 'light', step.findings.light))
    found.push(...tag(screen, 'focus', 'dark', step.findings.dark))
    found.push(...(await pixelFindings(page, screen, step.pixels, focused)))
    if (step.shoot !== null) focused.set(step.shoot, await pictures(page, step.shoot))
    if (!step.done && step.arrow !== null) {
      found.push(...(await arrowFindings(page, screen, step.arrow)))
    }
    if (!step.done) continue
    expect(step.stops, `${screen.id}: the walk is cut at ${WALK_LIMIT} stops`).toBeLessThan(
      WALK_LIMIT,
    )
    expect(step.stops, `${screen.id}: the walk found no stop`).toBeGreaterThan(0)
    return found
  }
}

/**
 * Every check on the screen in both themes; the focus walk last, since it moves the focus, and
 * the motion check once more after it, for what the walk set moving.
 */
export async function checkScreen(page: Page, screen: Screen): Promise<Finding[]> {
  const found: Finding[] = []
  for (const theme of ['light', 'dark'] as const) {
    await useTheme(page, theme)
    found.push(...(await motionFindings(page, screen, theme)))
    found.push(...(await axeFindings(page, screen, theme)))
  }
  found.push(...(await focusFindings(page, screen)))
  await call(page, 'settled')
  found.push(...(await motionFindings(page, screen, 'dark')))
  return found
}

function key(finding: Pick<Finding, 'screen' | 'check' | 'theme' | 'rule' | 'target'>): string {
  return [finding.screen, finding.check, finding.theme, finding.rule, finding.target].join(' | ')
}

function matches(known: Known, theme: Theme, finding: Finding): boolean {
  return (
    known.screen === finding.screen &&
    known.check === finding.check &&
    theme === finding.theme &&
    known.rule === finding.rule &&
    known.target === finding.target
  )
}

export interface Comparison {
  /** Found and not listed: each one fails the gate. */
  unlisted: Finding[]
  /** Listed and not found, per theme: each one fails the gate, so the lists only shrink. */
  gone: (Known & { theme: Theme })[]
}

/** Compares a screen's findings in `browser` with the known ones of that screen. */
export function compare(
  found: readonly Finding[],
  known: readonly Known[],
  browser: Browser,
): Comparison {
  const unique = [...new Map(found.map((finding) => [key(finding), finding])).values()]
  const expected: (Known & { theme: Theme })[] = []
  for (const entry of known) {
    if (entry.browser !== undefined && entry.browser !== browser) continue
    for (const theme of entry.theme === undefined ? (['light', 'dark'] as const) : [entry.theme]) {
      expected.push({ ...entry, theme })
    }
  }
  return {
    unlisted: unique.filter(
      (finding) => !expected.some((entry) => matches(entry, entry.theme, finding)),
    ),
    gone: expected.filter(
      (entry) => !unique.some((finding) => matches(entry, entry.theme, finding)),
    ),
  }
}

/** A finding as a known-list entry, for the report: paste it into `known/<area>.ts`. */
export function asKnown(finding: Finding): string {
  const entry: Known = {
    screen: finding.screen,
    check: finding.check,
    theme: finding.theme,
    rule: finding.rule,
    target: finding.target,
  }
  const note = finding.detail === undefined ? '' : ` // ${finding.detail.replaceAll('\n', ' ')}`
  return `${JSON.stringify(entry)},${note}`
}
