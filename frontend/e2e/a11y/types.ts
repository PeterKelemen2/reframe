import type { Page } from '@playwright/test'

export type Area = 'shell' | 'picture' | 'tracks'
export type Check = 'axe' | 'focus' | 'motion'
export type Theme = 'light' | 'dark'
/** The Playwright projects the gate runs in. */
export type Browser = 'chromium' | 'firefox' | 'webkit'

export interface Screen {
  /** Binding: the known lists and the reports name the screen by it. */
  id: string
  area: Area
  /** Brings the app to the screen through the UI, from a blank page (most start with `openApp`). */
  setup(page: Page): Promise<void>
  /**
   * The part of the page that is the screen (a dialog, a settings section): the focus walk
   * starts at its top and ends when the focus leaves it or comes back to its first stop.
   * Without it, the walk takes the whole page from its top. axe and the motion check always
   * take the whole page.
   */
  region?: string
}

/** A finding the gate expects on a screen, because it is not fixed yet. */
export interface Known {
  screen: string
  check: Check
  /** Without it, the finding is expected in both themes. */
  theme?: Theme
  /** Without it, the finding is expected in every browser. */
  browser?: Browser
  /** axe's rule id, or the gate's own rule (see `RULES`). */
  rule: string
  /** The element as the gate describes it (`probe.ts`, `describe`), exactly. */
  target: string
}

export interface Finding {
  screen: string
  check: Check
  theme: Theme
  rule: string
  target: string
  /** Shown in the report, never compared: a contrast, a property, axe's summary. */
  detail?: string
}

/** The gate's own rules, beside axe's. */
export const RULES = {
  focus: {
    'no-indicator': 'nothing on the page changes when the element takes the focus (2.4.7)',
    'indicator-contrast': 'the focus indicator has less than 3:1 against what it replaces (1.4.11)',
    obscured: 'something else covers the focused element at every point checked (2.4.11)',
    trap: 'Tab leaves the focus where it is while Tab stops are left unreached (2.1.2)',
    'region-exit': 'the focus leaves the region while Tab stops in it are left unreached (2.4.3)',
    unreached: 'a Tab stop that the walk round the region or the page never reached (2.1.1)',
  },
  axe: {
    'color-contrast-measured':
      'text below 4.5:1 (3:1 large) that axe left open, measured by the probe as painted (1.4.3)',
  },
  motion: {
    transition: 'a CSS transition ran',
    animation: 'a CSS animation with a duration ran',
    animate: 'a script started an animation with a duration',
    'frame-loop': "frame callbacks changed an element's style in many frames in a row",
    'smooth-scroll': 'something scrolls smoothly',
    running: 'an animation is running',
    'transition-duration': 'an element has a transition with a duration',
    'animation-duration': 'an element has an animation with a duration',
  },
} as const
