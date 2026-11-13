import type { Page } from '@playwright/test'

export type Area = 'shell' | 'picture' | 'tracks'
export type Check = 'axe' | 'focus' | 'motion'
export type Theme = 'light' | 'dark'
/** The Playwright projects the gate runs in. */
export type Browser = 'chromium' | 'firefox'

export interface Screen {
  /** Binding: the known lists and the reports name the screen by it. */
  id: string
  area: Area
  /** Brings the app to the screen through the UI, from a blank page (most start with `openApp`). */
  setup(page: Page): Promise<void>
  /**
   * The part of the page that is the screen (a dialog, a settings section): axe checks only it,
   * and the focus walk starts in it and ends when the focus leaves it. Without it, the whole
   * page, and the walk starts from where the set-up left the focus.
   */
  region?: string
}

/** A finding the gate expects on a screen, because it is not fixed yet. */
export interface Known {
  screen: string
  check: Check
  /** Without it, the finding is expected in both themes. */
  theme?: Theme
  /** Without it, the finding is expected in both browsers. */
  browser?: Browser
  /** axe's rule id, or the focus or motion rule (see `RULES`); without it, any rule. */
  rule?: string
  /** The element as the gate describes it (`probe.ts`, `describe`). */
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
  },
  motion: {
    transition: 'a CSS transition ran',
    animation: 'a CSS animation with a duration ran',
    animate: 'a script started an animation with a duration',
    'smooth-scroll': 'something scrolls smoothly',
    running: 'an animation is running',
    'transition-duration': 'an element has a transition with a duration',
    'animation-duration': 'an element has an animation with a duration',
  },
} as const
