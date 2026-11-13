import { test as plain } from '@playwright/test'

import { openApp } from '../support/app'
import { expect, test } from '../support/test'
import { axeFindings, compare, focusFindings, motionFindings, preparePage } from './gate'
import { goTo } from './steps'
import type { Finding, Screen } from './types'

// The gate's own checks, each against a page where the defect is put in on purpose.

const RAIL: Screen = { id: 'rail', area: 'shell', region: '.nav-rail', setup: openApp }
const WORKSPACE_LINK = 'nav.nav-rail a.nav-rail__link[data-view="workspace"]'

function rules(found: Finding[], target: string): string[] {
  return found.filter((f) => f.target === target).map((f) => `${f.theme} ${f.rule}`)
}

test('the focus walk reports a stop whose focus style is gone, and one that is too faint', async ({
  page,
}) => {
  await preparePage(page)
  await RAIL.setup(page)
  expect(await focusFindings(page, RAIL)).toEqual([])

  const style = await page.addStyleTag({
    content:
      '.nav-rail__link:focus-visible { outline: none !important; box-shadow: none !important }',
  })
  expect(rules(await focusFindings(page, RAIL), WORKSPACE_LINK)).toEqual([
    'light no-indicator',
    'dark no-indicator',
  ])

  await style.evaluate((node) => Reflect.get(node, 'remove').call(node))
  // A ring the colour of the rail's background in either theme.
  await page.addStyleTag({
    content:
      '.nav-rail__link:focus-visible { outline-color: var(--p-content-background) !important }',
  })
  expect(rules(await focusFindings(page, RAIL), WORKSPACE_LINK)).toEqual([
    'light indicator-contrast',
    'dark indicator-contrast',
  ])
})

test('the motion check reports a transition, a script animation and a smooth scroll', async ({
  page,
}) => {
  await preparePage(page)
  await openApp(page)
  await goTo(page, 'Settings')
  const screen: Screen = { id: 'settings', area: 'shell', setup: openApp }
  expect(await motionFindings(page, screen, 'light')).toEqual([])

  // More specific than the reduced-motion rule of tokens.css, which a component could be.
  await page.addStyleTag({ content: 'html body .nav-rail { transition: color 2s !important }' })
  await page.evaluate(() => {
    // This file is type-checked without the DOM library.
    type Box = { animate(frames: object[], ms: number): void; scrollIntoView(o: object): void }
    const doc = Reflect.get(globalThis, 'document') as { querySelector(s: string): Box | null }
    doc.querySelector('.nav-rail')?.animate([{ opacity: 0.5 }, { opacity: 1 }], 5000)
    doc.querySelector('[data-section="appearance"]')?.scrollIntoView({ behavior: 'smooth' })
  })
  // A call reports what moved since the last one: the rules add up over the calls.
  const seen = new Set<string>()
  await expect
    .poll(async () => {
      for (const found of await motionFindings(page, screen, 'light')) seen.add(found.rule)
      return [...seen].toSorted()
    })
    .toEqual(['animate', 'running', 'smooth-scroll', 'transition-duration'])
})

test('axe reports text below 4.5:1, at the element that has it', async ({ page }) => {
  await preparePage(page)
  await openApp(page)
  const screen: Screen = { id: 'empty', area: 'shell', setup: openApp }
  expect(await axeFindings(page, screen, 'light')).toEqual([])
  await page.addStyleTag({ content: '.workspace__empty-text { color: #b0b0b0 !important }' })
  const found = await axeFindings(page, screen, 'light')
  expect(found.map((f) => `${f.rule} ${f.target}`)).toContain(
    'color-contrast #app p.workspace__empty-text',
  )
})

function finding(theme: 'light' | 'dark', target = 'a'): Finding {
  return { screen: 's', check: 'axe', theme, rule: 'color-contrast', target }
}

plain.describe('compare', () => {
  plain('an entry without a theme stands for both themes', () => {
    const known = [{ screen: 's', check: 'axe' as const, target: 'a' }]
    expect(compare([finding('light'), finding('dark')], known, 'chromium')).toEqual({ unlisted: [], gone: [] })
    expect(compare([finding('light')], known, 'chromium').gone).toEqual([{ ...known[0], theme: 'dark' }])
  })

  plain('fails on a finding that is not listed and on a listed one that is gone', () => {
    const known = [{ screen: 's', check: 'axe' as const, theme: 'light' as const, target: 'b' }]
    const { unlisted, gone } = compare([finding('light', 'a'), finding('light', 'a')], known, 'chromium')
    expect(unlisted).toEqual([finding('light', 'a')])
    expect(gone).toEqual(known)
  })

  plain('an entry of one browser is expected in that browser only', () => {
    const known = [{ screen: 's', check: 'axe' as const, browser: 'firefox' as const, target: 'a' }]
    expect(compare([], known, 'chromium')).toEqual({ unlisted: [], gone: [] })
    expect(compare([], known, 'firefox').gone).toHaveLength(2)
    expect(compare([finding('light')], known, 'chromium').unlisted).toEqual([finding('light')])
  })

  plain('an entry with a rule matches that rule only', () => {
    const known = [
      { screen: 's', check: 'axe' as const, theme: 'light' as const, rule: 'other', target: 'a' },
    ]
    expect(compare([finding('light')], known, 'chromium').unlisted).toEqual([finding('light')])
  })
})
