/* oxlint-disable eslint/no-await-in-loop -- the checks, and the Tabs of a walk, take turns on one page */
import { AxeBuilder } from '@axe-core/playwright'
import { expect, type Page } from '@playwright/test'

import { DARK_MODE_CLASS } from '../../src/styles/theme'
import { PROBE_GLOBAL, type ProbeApi, type ProbeFinding } from './probeApi'
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
  await call(page, 'frames')
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

export async function axeFindings(page: Page, screen: Screen, theme: Theme): Promise<Finding[]> {
  let builder = new AxeBuilder({ page }).withTags(WCAG_TAGS)
  if (screen.region !== undefined) builder = builder.include(screen.region)
  const { violations } = await builder.analyze()
  const nodes = violations.flatMap((violation) =>
    violation.nodes.map((node) => ({
      rule: violation.id,
      selector: node.target.map((part) => (Array.isArray(part) ? part.join(' ') : part)).join(' '),
      detail: node.failureSummary?.split('\n').slice(1).join(' ').trim(),
    })),
  )
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

/**
 * Tabs through the screen and judges each stop in both themes once the focus has left it: its
 * focused paint against its unfocused paint (`probe.ts`).
 */
export async function focusFindings(page: Page, screen: Screen): Promise<Finding[]> {
  const found: Finding[] = []
  const region = screen.region ?? null
  if (region !== null) {
    expect(await call(page, 'enterRegion', region), `the region ${region}`).toBe(true)
  }
  await call(page, 'walkStart', DARK_MODE_CLASS, WALK_LIMIT, region)
  for (;;) {
    await page.keyboard.press('Tab')
    if (region !== null) await call(page, 'leaveRegion', region)
    let step = await call(page, 'walkStep')
    if (step.settle) {
      await page.waitForTimeout(SETTLE_MS)
      step = await call(page, 'walkStep')
    }
    found.push(...tag(screen, 'focus', 'light', step.findings.light))
    found.push(...tag(screen, 'focus', 'dark', step.findings.dark))
    if (!step.done) continue
    expect(step.stops, `${screen.id}: the walk is cut at ${WALK_LIMIT} stops`).toBeLessThan(
      WALK_LIMIT,
    )
    expect(step.stops, `${screen.id}: the walk found no stop`).toBeGreaterThan(0)
    return found
  }
}

/** Every check on the screen in both themes; the focus walk last, since it moves the focus. */
export async function checkScreen(page: Page, screen: Screen): Promise<Finding[]> {
  const found: Finding[] = []
  for (const theme of ['light', 'dark'] as const) {
    await useTheme(page, theme)
    found.push(...(await motionFindings(page, screen, theme)))
    found.push(...(await axeFindings(page, screen, theme)))
  }
  found.push(...(await focusFindings(page, screen)))
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
    (known.rule === undefined || known.rule === finding.rule) &&
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
