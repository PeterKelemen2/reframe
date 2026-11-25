import { test as plain, type Page } from '@playwright/test'

import { openApp } from '../support/app'
import { expect, test } from '../support/test'
import {
  axeFindings,
  checkScreen,
  compare,
  focusFindings,
  motionFindings,
  preparePage,
} from './gate'
import { screens as pictureScreens } from './screens/picture'
import { screens as shellScreens } from './screens/shell'
import { screens as tracksScreens } from './screens/tracks'
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

test('the focus walk measures a ring against a translucent background as it is painted', async ({
  page,
}) => {
  await preparePage(page)
  await RAIL.setup(page)
  // The rail is white at 50 % over black: mid grey (128) is what a ring outside a link lies on.
  await page.addStyleTag({
    content: `
      html, body, *:has(.nav-rail) { background: #000 !important }
      .nav-rail { background: rgb(255 255 255 / 50%) !important }
      .nav-rail * { background: transparent !important }
      .nav-rail__link:focus-visible {
        outline: 2px solid var(--test-ring) !important;
        outline-offset: 2px !important;
        box-shadow: none !important;
      }`,
  })
  const ring = (colour: string) =>
    page.evaluate((value) => {
      const doc = Reflect.get(globalThis, 'document') as {
        documentElement: { style: { setProperty(name: string, value: string): void } }
      }
      doc.documentElement.style.setProperty('--test-ring', value)
    }, colour)

  // White on mid grey is 3.95:1. Read as if the tint were premultiplied, the grey turns white.
  await ring('#fff')
  expect(rules(await focusFindings(page, RAIL), WORKSPACE_LINK)).toEqual([])
  // Light grey (200) on mid grey is 2.36:1.
  await ring('rgb(200 200 200)')
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
  await page.addStyleTag({
    content:
      'html body .nav-rail { transition: color 2s !important } html body * { scroll-behavior: smooth !important }',
  })
  await page.evaluate(() => {
    // This file is type-checked without the DOM library.
    type Box = { animate(frames: object[], ms: number): void; scrollIntoView(o: object): void }
    const doc = Reflect.get(globalThis, 'document') as { querySelector(s: string): Box | null }
    doc.querySelector('.nav-rail')?.animate([{ opacity: 0.5 }, { opacity: 1 }], 5000)
    // The app turns a smooth scroll that code asks for into a jump; a stylesheet's is left.
    doc.querySelector('[data-section="appearance"]')?.scrollIntoView({})
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

// The app's screens broken where a narrower gate did not look: the whole page behind a region,
// the workspace with a file open, the set-up's own focused element, an option an arrow reaches.

const SCREENS = [...shellScreens, ...pictureScreens, ...tracksScreens]
const prepared = new WeakSet<Page>()

async function prepareOnce(page: Page): Promise<void> {
  if (!prepared.has(page)) await preparePage(page)
  prepared.add(page)
}

function screenOf(id: string): Screen {
  const found = SCREENS.find((each) => each.id === id)
  if (found === undefined) throw new Error(`no screen ${id}`)
  return found
}

async function broken(page: Page, id: string, css: string): Promise<Screen> {
  const shown = screenOf(id)
  await prepareOnce(page)
  await shown.setup(page)
  await page.addStyleTag({ content: css })
  return shown
}

/** The light findings of `rule` whose target holds `part`. */
function hits(found: Finding[], rule: string, part: string): string[] {
  return found
    .filter((f) => f.theme === 'light' && f.rule === rule && f.target.includes(part))
    .map((f) => f.target)
}

/** The light focus findings (no indicator, or one too faint) whose target holds `part`. */
function unseen(found: Finding[], part: string): string[] {
  return [...hits(found, 'no-indicator', part), ...hits(found, 'indicator-contrast', part)]
}

const NO_RING = 'outline: none !important; box-shadow: none !important'

test('the walk of a whole page reaches the workspace header, the sources and the editor tabs', async ({
  page,
}) => {
  const shown = await broken(
    page,
    'toast',
    `.workspace__header *:focus-visible, .sources-panel__source:focus-visible { ${NO_RING} }
     .editor-tabs .p-tab:focus-visible { ${NO_RING}; border-color: transparent !important }
     .editor-tabs .p-tab:focus-visible::after { background: none !important }`,
  )
  const found = await focusFindings(page, shown)
  expect(unseen(found, 'workspace__header')).not.toEqual([])
  expect(unseen(found, 'sources-panel__source')).not.toEqual([])
  expect(unseen(found, 'editor-tabs')).not.toEqual([])
})

test('the walk judges the element the set-up left the focus on', async ({ page }) => {
  // The field's ink border on focus is an indicator of its own: it goes too.
  const shown = await broken(
    page,
    'login',
    `.login-screen__input:focus-visible { ${NO_RING};
       border-color: var(--p-form-field-border-color) !important }`,
  )
  expect(unseen(await focusFindings(page, shown), 'login-screen__input')).not.toEqual([])
})

test('the walk judges the file browser entry an arrow key points at', async ({ page }) => {
  const shown = await broken(
    page,
    'file-browser',
    `.file-browser__entry--cursor { ${NO_RING}; border-color: transparent !important;
       background: transparent !important }`,
  )
  expect(unseen(await focusFindings(page, shown), 'file-browser__entry')).not.toEqual([])
})

const PAST_REGIONS: [string, string, string, string][] = [
  ['the sources tree under a dialog', 'matrix', '.sources-panel__group-name', 'sources-panel'],
  ['the settings links', 'settings-tools', '.settings-view__link', 'settings-view__link'],
  [
    'the status bar in its error state',
    'status-issues',
    '.validation-summary__part--error, .validation-summary__part--error *',
    'validation-summary',
  ],
]

for (const [what, id, selector, part] of PAST_REGIONS) {
  test(`axe looks past the region: ${what}`, async ({ page }) => {
    const shown = await broken(page, id, `${selector} { color: #c0c0c0 !important }`)
    expect(hits(await axeFindings(page, shown, 'light'), 'color-contrast', part)).not.toEqual([])
  })
}

test('the settings page is walked with its links', async ({ page }) => {
  const shown = await broken(page, 'settings', `.settings-view__link:focus-visible { ${NO_RING} }`)
  expect(unseen(await focusFindings(page, shown), 'settings-view__link')).not.toEqual([])
})

test('the motion check looks again after the walk', async ({ page }) => {
  await preparePage(page)
  await RAIL.setup(page)
  await page.addStyleTag({
    content: 'html body .nav-rail__link:focus-visible { transition: outline-color 2s !important }',
  })
  // Only a focused link has the transition: the checks before the walk see none.
  const moved = (await checkScreen(page, RAIL)).filter(
    (f) => f.check === 'motion' && f.rule === 'transition',
  )
  expect(moved.map((f) => `${f.theme} ${f.target}`)).toContain(`dark ${WORKSPACE_LINK}`)
})

// Pages made for one defect each: what the probe must see on a page whose paint is known.

const PAGE_CSS = `
  html, body { margin: 0; background: #fff; color: #111; font: 16px sans-serif }
  html.reframe-dark, html.reframe-dark body { background: #fff; color: #111 }
  :focus-visible { outline: 2px solid #4338ca; outline-offset: 2px }
  .row { padding: 24px; display: flex; gap: 16px }
  button { font: inherit; padding: 6px 12px; border: 1px solid #555; background: #fff; color: #111 }
`
const WHOLE: Screen = { id: 'page', area: 'shell', setup: async () => {} }

async function made(page: Page, css: string, body: string, script = ''): Promise<void> {
  await page.route('**/gate-made-page', (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><html lang="en"><head><title>Gate</title><style>${PAGE_CSS}${css}</style></head><body><main>${body}</main><script>${script}</script></body></html>`,
    }),
  )
  await prepareOnce(page)
  await page.goto('/gate-made-page')
}

/** The findings as `theme rule target`, light ones only: the pages paint both themes alike. */
function light(found: Finding[]): string[] {
  return found.filter((f) => f.theme === 'light').map((f) => `${f.rule} ${f.target}`)
}

const TWO_BUTTONS =
  '<div class="row"><button id="one">One</button><button id="two">Two</button></div>'

test('a good page gives the focus walk nothing to report', async ({ page }) => {
  await made(page, '', TWO_BUTTONS)
  expect(await focusFindings(page, WHOLE)).toEqual([])
})

test('a change of a box round several stops is no indicator for any of them', async ({ page }) => {
  await made(
    page,
    `.bar { border: 2px solid #ccc; display: flex; gap: 4px; padding: 4px; margin: 24px }
     .bar:focus-within { border-color: #000 }
     .bar button:focus-visible { outline: none }`,
    '<div class="bar"><button id="cut">Cut</button><button id="copy">Copy</button></div>',
  )
  expect(light(await focusFindings(page, WHOLE))).toEqual([
    'no-indicator #cut',
    'no-indicator #copy',
  ])
})

test('a ring is measured faded by the opacity of an ancestor', async ({ page }) => {
  await made(page, '.faded { opacity: 0.25 }', TWO_BUTTONS.replace('row', 'row faded'))
  expect(light(await focusFindings(page, WHOLE))).toEqual([
    'indicator-contrast #one',
    'indicator-contrast #two',
  ])
})

test('a ring is measured against a gradient painted over the background colour', async ({
  page,
}) => {
  await made(
    page,
    `.row { background-color: #000; background-image: linear-gradient(#fff, #fff) }
     .row button { background: #222; color: #fff; border-color: #222 }
     .row button:focus-visible { outline: 2px solid #fff; outline-offset: 3px }`,
    TWO_BUTTONS,
  )
  expect(light(await focusFindings(page, WHOLE))).toEqual([
    'indicator-contrast #one',
    'indicator-contrast #two',
  ])
})

test('a ring that an ancestor clips away is no ring', async ({ page }) => {
  await made(
    page,
    '.clip { overflow: hidden; display: inline-flex; margin: 24px } .clip button { margin: 0 }',
    '<div class="clip"><button id="one">One</button></div><div class="clip"><button id="two">Two</button></div>',
  )
  expect(light(await focusFindings(page, WHOLE))).toEqual([
    'indicator-contrast #one',
    'indicator-contrast #two',
  ])
})

test('a ring is measured where the stop can be seen, while it has the focus', async ({ page }) => {
  // The next Tab scrolls the first button out of view before it is judged; the tall box is
  // seen only in part, its ring on the sides in view.
  await made(
    page,
    `.scroller { height: 120px; overflow: auto; margin: 24px; padding: 8px }
     .tall { height: 600px; margin: 4px }`,
    `<div class="scroller"><button id="one">One</button><div class="tall" id="tall" tabindex="0"></div>
       <button id="two">Two</button></div>`,
  )
  expect(await focusFindings(page, WHOLE)).toEqual([])
})

test('a ring seen on one side only does not pass', async ({ page }) => {
  await made(
    page,
    `.row { gap: 0 } .block { width: 40px; background: #000 }
     button:focus-visible { outline: 2px solid #fff; outline-offset: 0 }`,
    '<div class="row"><button id="one">One</button><span class="block"></span></div>',
  )
  expect(light(await focusFindings(page, WHOLE))).toEqual(['indicator-contrast #one'])
})

function onPicture(ring: string): string {
  return `
    html, body { background: #000 }
    main { position: relative; margin: 24px }
    #on { position: absolute; left: 100px; top: 40px; background: #222; color: #fff; border-color: #222 }
    #on:focus-visible { outline: 2px solid ${ring}; outline-offset: 3px }`
}

test('a ring over a picture is judged by its pixels', async ({ page }) => {
  const canvas = `<canvas id="picture" width="300" height="120"></canvas><button id="on">On it</button>`
  const draw = `const g = document.getElementById('picture').getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 300, 120)`
  await made(page, onPicture('#000'), canvas, draw)
  expect(await focusFindings(page, WHOLE)).toEqual([])
  // White on the white picture: its computed backdrop (the black page) would say 21:1.
  await made(page, onPicture('#fff'), canvas, draw)
  expect(light(await focusFindings(page, WHOLE))).toEqual(['no-indicator #on'])
})

/** `onPicture`'s page with a rounded stop on a half CSS pixel, and its focus style. */
function onHalfPixel(focus: string): string {
  return `${onPicture('#000')} #on { left: 100.5px; top: 40.5px; border-radius: 4px }
    #on:focus-visible { ${focus} }`
}

test.describe('on a screen with two device pixels to the CSS pixel', () => {
  test.use({ deviceScaleFactor: 2 })

  test('a ring on a half CSS pixel is judged as painted', async ({ page }) => {
    const canvas = `<canvas id="picture" width="300" height="120"></canvas><button id="on">On it</button>`
    const draw = `const g = document.getElementById('picture').getContext('2d'); g.fillStyle = '#777'; g.fillRect(0, 0, 300, 120)`
    // Crisp in device pixels; WebKit's picture in CSS pixels blends it into a 2.5:1 grey.
    await made(page, onHalfPixel('outline-width: 1px'), canvas, draw)
    expect(await focusFindings(page, WHOLE)).toEqual([])
    await made(page, onHalfPixel('outline: 1px solid #555'), canvas, draw)
    expect(light(await focusFindings(page, WHOLE))).toEqual(['indicator-contrast #on'])
    // A line under the stop: four device pixels to each CSS pixel of it.
    await made(page, onHalfPixel('outline: none; box-shadow: 0 2px 0 #000'), canvas, draw)
    expect(light(await focusFindings(page, WHOLE))).toEqual(['indicator-contrast #on'])
  })
})

test('an overlay that lets the pointer through still hides a stop', async ({ page }) => {
  const cover = '<div class="cover"></div>'
  const css = '.cover { position: fixed; inset: 0; background: #fff; pointer-events: none }'
  await made(page, css, `${TWO_BUTTONS}${cover}`)
  expect(light(await focusFindings(page, WHOLE))).toContain('obscured #one')
  await made(page, `${css} .cover { inset: auto; width: 0; height: 0 }`, TWO_BUTTONS + cover)
  expect(await focusFindings(page, WHOLE)).toEqual([])
})

/** A script that brings `.late` into view when `#one` gets the focus, called through `when`. */
function revealLate(when: string): string {
  return `document.getElementById('one').addEventListener('focus', () => ${when}(() => document.querySelector('.late').style.top = '24px'))`
}

test('a stop that comes into view at the next rendering update is not hidden', async ({ page }) => {
  // As WebKit reveals a focused field: in the second frame callback after the Tab, not in it.
  const css = '.late { position: fixed; left: 24px; top: 200vh }'
  const late = '<div class="late"><button id="one">One</button></div>'
  const secondFrame = '((f) => requestAnimationFrame(() => requestAnimationFrame(f)))'
  await made(page, css, late, revealLate(secondFrame))
  expect(await focusFindings(page, WHOLE)).toEqual([])
  await made(page, css, late, revealLate('((f) => setTimeout(f, 500))'))
  expect(light(await focusFindings(page, WHOLE))).toContain('obscured #one')
})

test('a stop that keeps the focus on Tab is a trap', async ({ page }) => {
  await made(
    page,
    '',
    '<div class="row"><button>One</button><button id="trap">Two</button><button>Three</button></div>',
    `document.getElementById('trap').addEventListener('keydown', (e) => { if (e.key === 'Tab') e.preventDefault() })`,
  )
  expect(light(await focusFindings(page, WHOLE))).toEqual(['trap #trap'])
})

test('a focus that leaves a region before its last stop is reported', async ({ page }) => {
  await made(
    page,
    '',
    '<div class="row box"><button id="one">One</button><button>Two</button></div><button id="out">Out</button>',
    `document.getElementById('one').addEventListener('keydown', (e) => { if (e.key === 'Tab') { e.preventDefault(); document.getElementById('out').focus() } })`,
  )
  expect(light(await focusFindings(page, { ...WHOLE, region: '.box' }))).toEqual([
    'region-exit #one',
  ])
})

test('a stop that the walk round a region never reaches is reported', async ({ page }) => {
  await made(
    page,
    '',
    '<div class="row box"><button id="one">One</button><button id="two">Two</button><button id="three">Three</button></div>',
    `document.getElementById('two').addEventListener('keydown', (e) => { if (e.key === 'Tab') { e.preventDefault(); document.getElementById('one').focus() } })`,
  )
  expect(light(await focusFindings(page, { ...WHOLE, region: '.box' }))).toEqual([
    'unreached #three',
  ])
})

const LISTBOX = `<div class="row"><div id="list" role="listbox" tabindex="0" aria-label="Letters" aria-activedescendant="alpha"><div role="option" id="alpha" class="option cursor">A</div><div role="option" id="beta" class="option">B</div></div></div>`
const LISTBOX_KEYS = `const list = document.getElementById('list')
  list.addEventListener('keydown', (e) => {
    const options = [...list.querySelectorAll('[role=option]')]
    const at = options.findIndex((o) => o.id === list.getAttribute('aria-activedescendant'))
    const to = e.key === 'ArrowDown' ? at + 1 : e.key === 'ArrowUp' ? at - 1 : at
    if (to === at || to < 0 || to >= options.length) return
    e.preventDefault()
    options[at].classList.remove('cursor')
    options[to].classList.add('cursor')
    list.setAttribute('aria-activedescendant', options[to].id)
  })`

test('the option a list points at shows the focus, the one an arrow key reaches too', async ({
  page,
}) => {
  const cursor = '#list:focus .cursor { outline: 2px solid #4338ca; outline-offset: -2px }'
  await made(page, cursor, LISTBOX, LISTBOX_KEYS)
  expect(await focusFindings(page, WHOLE)).toEqual([])
  // A bar on one side only: its own width counts, not the top border's.
  const bar =
    '.option { border-left: 3px solid transparent } #list:focus .cursor { border-left-color: #4338ca }'
  await made(page, bar, LISTBOX, LISTBOX_KEYS)
  expect(await focusFindings(page, WHOLE)).toEqual([])
  await made(page, '', LISTBOX, LISTBOX_KEYS)
  expect(light(await focusFindings(page, WHOLE))).toEqual([
    'no-indicator #alpha',
    'no-indicator #beta',
  ])
})

test('a tab that only an arrow key reaches is judged', async ({ page }) => {
  await made(
    page,
    '#second:focus-visible { outline: none }',
    '<div class="row" role="tablist"><button role="tab" id="first" aria-selected="true">One</button><button role="tab" id="second" tabindex="-1" aria-selected="false">Two</button></div>',
    `const tabs = [...document.querySelectorAll('[role=tab]')]
     for (const tab of tabs) tab.addEventListener('keydown', (e) => {
       if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
       const at = tabs.indexOf(tab)
       tabs[(at + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length].focus()
     })`,
  )
  expect(light(await focusFindings(page, WHOLE))).toEqual(['no-indicator #second'])
})

test('the motion check sees an animation started by hand and a script tween', async ({ page }) => {
  await made(
    page,
    '#box, #bar { width: 50px; height: 10px; background: #000 }',
    '<div id="box"></div><div id="bar"></div>',
    `new Animation(new KeyframeEffect(document.getElementById('box'), [{ opacity: 0 }, { opacity: 1 }], 100)).play()
     let w = 10
     ;(function step() { w = (w + 2) % 400; document.getElementById('bar').style.width = w + 'px'; requestAnimationFrame(step) })()`,
  )
  const seen = new Set<string>()
  await expect
    .poll(async () => {
      for (const found of await motionFindings(page, WHOLE, 'light'))
        seen.add(`${found.rule} ${found.target}`)
      return [...seen].filter((rule) => !rule.startsWith('running')).toSorted()
    })
    .toEqual(['animate #box', 'frame-loop #bar'])
})

function tinted(color: string): string {
  return `.tinted { background-image: linear-gradient(#fff, #f4f4f4); color: ${color}; padding: 8px }`
}

test('axe text contrast left open over a gradient is measured', async ({ page }) => {
  const body = '<p class="tinted">Some words on a gradient</p>'
  await made(page, tinted('#111'), body)
  expect(await axeFindings(page, WHOLE, 'light')).toEqual([])
  await made(page, tinted('#aaa'), body)
  expect(light(await axeFindings(page, WHOLE, 'light'))).toEqual([
    'color-contrast-measured p.tinted',
  ])
})

function finding(theme: 'light' | 'dark', target = 'a'): Finding {
  return { screen: 's', check: 'axe', theme, rule: 'color-contrast', target }
}

plain.describe('compare', () => {
  plain('an entry without a theme stands for both themes', () => {
    const known = [{ screen: 's', check: 'axe' as const, rule: 'color-contrast', target: 'a' }]
    expect(compare([finding('light'), finding('dark')], known, 'chromium')).toEqual({
      unlisted: [],
      gone: [],
    })
    expect(compare([finding('light')], known, 'chromium').gone).toEqual([
      { ...known[0], theme: 'dark' },
    ])
  })

  plain('fails on a finding that is not listed and on a listed one that is gone', () => {
    const known = [
      {
        screen: 's',
        check: 'axe' as const,
        theme: 'light' as const,
        rule: 'color-contrast',
        target: 'b',
      },
    ]
    const { unlisted, gone } = compare(
      [finding('light', 'a'), finding('light', 'a')],
      known,
      'chromium',
    )
    expect(unlisted).toEqual([finding('light', 'a')])
    expect(gone).toEqual(known)
  })

  plain('an entry of one browser is expected in that browser only', () => {
    const known = [
      {
        screen: 's',
        check: 'axe' as const,
        browser: 'firefox' as const,
        rule: 'color-contrast',
        target: 'a',
      },
    ]
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

  plain('an entry matches its whole target only', () => {
    const known = [
      {
        screen: 's',
        check: 'axe' as const,
        theme: 'light' as const,
        rule: 'color-contrast',
        target: 'a',
      },
    ]
    expect(compare([finding('light', 'a b')], known, 'chromium').unlisted).toEqual([
      finding('light', 'a b'),
    ])
  })
})
