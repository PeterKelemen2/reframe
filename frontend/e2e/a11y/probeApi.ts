/** A finding as the page sees it; the gate adds the screen, the check and the theme. */
export interface ProbeFinding {
  rule: string
  target: string
  /** What the gate prints beside the finding (a contrast, a property); not compared. */
  detail?: string
}

export type ThemeName = 'light' | 'dark'

/** Findings per theme. */
export interface ThemeFindings {
  light: ProbeFinding[]
  dark: ProbeFinding[]
}

/** A part of the window to take a picture of, in CSS pixels. */
export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

/** Where a stop judged by its pixels was when a picture was taken. */
export interface ShotPlace {
  /** The picture's area: the stop and a margin around it, inside the window. */
  clip: Rect
  /** The stop's own box. */
  box: Rect
  /** The part of the stop that can be seen: its indicator is measured against its size. */
  seen: Rect
}

export interface WalkStep {
  /**
   * The walk is over: the focus came back to its first stop, left the page or the region, or
   * stayed put.
   */
  done: boolean
  /**
   * The last stop had no unfocused look from before the walk: call again after a moment, once
   * its blur has settled, to judge it.
   */
  settle: boolean
  /** The stops the walk has seen so far. */
  stops: number
  findings: ThemeFindings
  /** Stops that left the focus and are judged by their pixels: take their unfocused pictures. */
  pixels: number[]
  /** The new stop is judged by its pixels: take its focused pictures now. */
  shoot: number | null
  /** The arrow key that moves the focus inside the new stop's widget, if it is one. */
  arrow: string | null
}

/** What `page/probe.ts` installs in the page as `__reframeA11y`. */
export interface ProbeApi {
  /** The descriptions (`describe` in `page/probe.ts`) of the elements the selectors find. */
  describeAll(selectors: string[]): string[]
  /** What moved since the last call, and what can move now. */
  motion(): ProbeFinding[]
  /** Resolves once what started moves has begun, and a smooth scroll has been seen. */
  settled(): Promise<void>
  /** Focuses the element itself, so that the next Tab goes to its first stop; false if absent. */
  enterRegion(selector: string): boolean
  /** Undoes what `enterRegion` changed on the element. */
  leaveRegion(selector: string): void
  /** Starts a walk; with a region, it ends when the focus leaves the region. */
  walkStart(darkClass: string, limit: number, region: string | null): void
  /** Called after each Tab. */
  walkStep(): WalkStep
  /** Called after an arrow key: whether the focus moved to another item of the stop's widget. */
  arrowSeen(): boolean
  /** Called once the arrow's opposite has brought the focus back: judges the item it visited. */
  arrowBack(): ThemeFindings
  /** Shows the page in `theme`, or in its own theme again for null. */
  setTheme(theme: ThemeName | null): void
  /** Whether the stop judged by pixels looks as before the walk again: its blur has settled. */
  looksPlain(key: number): boolean
  /** Where to take the picture of the stop that `WalkStep.shoot` or `.pixels` named. */
  shotPlace(key: number): ShotPlace | null
  /** Judges a stop by its focused and unfocused pictures (base64 PNG). */
  comparePixels(
    key: number,
    focused: { png: string; place: ShotPlace },
    unfocused: { png: string; place: ShotPlace },
  ): Promise<ProbeFinding | null>
  /**
   * The text contrast of each element the selectors find, as painted, against the contrast it
   * needs; `skip` says why it cannot be measured.
   */
  measureText(selectors: string[]): { ratio: number; need: number; skip?: string }[]
}

/** The property of `window` that holds the probe. */
export const PROBE_GLOBAL = '__reframeA11y'
