/** A finding as the page sees it; the gate adds the screen, the check and the theme. */
export interface ProbeFinding {
  rule: string
  target: string
  /** What the gate prints beside the finding (a contrast, a property); not compared. */
  detail?: string
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
  findings: { light: ProbeFinding[]; dark: ProbeFinding[] }
}

/** What `page/probe.ts` installs in the page as `__reframeA11y`. */
export interface ProbeApi {
  /** The descriptions (`describe` in `page/probe.ts`) of the elements the selectors find. */
  describeAll(selectors: string[]): string[]
  /** What moved since the last call, and what can move now. */
  motion(): ProbeFinding[]
  /** Resolves after two frames: a transition started before has begun by then. */
  frames(): Promise<void>
  /** Focuses the region itself, so that the next Tab goes to its first stop; false if absent. */
  enterRegion(selector: string): boolean
  /** Undoes what `enterRegion` changed on the region. */
  leaveRegion(selector: string): void
  /** Starts a walk; with a region, it ends when the focus leaves the region. */
  walkStart(darkClass: string, limit: number, region: string | null): void
  /** Called after each Tab. */
  walkStep(): WalkStep
}

/** The property of `window` that holds the probe. */
export const PROBE_GLOBAL = '__reframeA11y'
