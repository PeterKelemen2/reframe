// One timed run of the magnifier: every animation frame's interval, and the redraw's own time
// for each frame that had a new pointer position. Pointer events only store the position; the
// redraw happens once per animation frame.

/** The pointer path of every case: an ellipse over the main canvas, one turn every 2 s. */
export const PATH = { turn: 2000, radius: 0.4, eventEvery: 8 };

/** The point of the path `elapsed` ms after the start, in the canvas's CSS pixels. */
export function pathPoint(elapsed, width, height) {
  const angle = (2 * Math.PI * elapsed) / PATH.turn;
  return {
    x: width / 2 + PATH.radius * width * Math.cos(angle),
    y: height / 2 + PATH.radius * height * Math.sin(angle),
  };
}

export class Run {
  constructor(label, mode, seconds, redraw) {
    this.label = label;
    this.mode = mode;
    this.seconds = seconds;
    this.redraw = redraw;
    this.intervals = [];
    this.draws = [];
    this.frames = 0;
    this.events = 0;
    this.trusted = 0;
    this.pointerTypes = {};
    this.dirty = false;
    this.position = null;
    this.last = null;
    this.started = null;
    this.done = new Promise((resolve) => (this.finish = resolve));
  }

  /** Starts the frame loop; the run ends `seconds` after this call. */
  start() {
    this.started = performance.now();
    requestAnimationFrame((time) => this.frame(time));
  }

  pointer(event, position) {
    this.events += 1;
    if (event.isTrusted) this.trusted += 1;
    this.pointerTypes[event.pointerType || "none"] = (this.pointerTypes[event.pointerType || "none"] || 0) + 1;
    this.position = position;
    this.dirty = true;
  }

  frame(time) {
    if (this.last !== null) this.intervals.push(round(time - this.last));
    this.last = time;
    this.frames += 1;
    if (this.dirty) {
      this.dirty = false;
      const before = performance.now();
      this.redraw(this.position);
      this.draws.push(round(performance.now() - before));
    }
    if (performance.now() - this.started < this.seconds * 1000) {
      requestAnimationFrame((next) => this.frame(next));
    } else {
      this.finish(this.record());
    }
  }

  record() {
    const elapsed = performance.now() - this.started;
    return {
      check: "magnifier",
      type: "run",
      label: this.label,
      mode: this.mode,
      seconds: round(elapsed / 1000),
      frames: this.frames,
      events: this.events,
      events_per_second: round(this.events / (elapsed / 1000)),
      trusted: this.trusted,
      pointer_types: this.pointerTypes,
      intervals: this.intervals,
      draws: this.draws,
    };
  }
}

/**
 * Moves along the path with synthetic `pointermove` events dispatched on `target` by the page
 * itself, one every `PATH.eventEvery` ms, until `run` ends.
 */
export function drivePage(run, target) {
  const rect = target.getBoundingClientRect();
  const started = performance.now();
  let stopped = false;
  run.done.then(() => (stopped = true));
  const step = () => {
    if (stopped) return;
    const point = pathPoint(performance.now() - started, rect.width, rect.height);
    target.dispatchEvent(
      new PointerEvent("pointermove", {
        clientX: rect.left + point.x,
        clientY: rect.top + point.y,
        bubbles: true,
        pointerType: "mouse",
        isPrimary: true,
      }),
    );
    setTimeout(step, PATH.eventEvery);
  };
  step();
}

/** The smallest step of `performance.now()` seen in a short busy loop (its resolution). */
export function clockStep() {
  let smallest = Infinity;
  let last = performance.now();
  for (let i = 0; i < 200000 && smallest > 0.001; i += 1) {
    const now = performance.now();
    if (now > last) {
      smallest = Math.min(smallest, now - last);
      last = now;
    }
  }
  return round(smallest);
}

function round(value) {
  return Math.round(value * 1000) / 1000;
}
