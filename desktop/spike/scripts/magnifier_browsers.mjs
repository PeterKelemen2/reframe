// The magnifier page in one Playwright browser. It prints every record the page logs as one JSON
// line at once (the check script reads them while it moves the real pointer), runs the
// page-driven runs, then `--playwright-runs` runs moved with page.mouse.move, then waits for
// `--real-runs` runs that the check script makes with the real pointer, then takes a screenshot.
// node scripts/magnifier_browsers.mjs <page url> <engine> <screenshot path>
//   [--headed --exe=<path>] [--playwright-runs=3] [--real-runs=0]
import { chromium, firefox } from "playwright";

import { PATH, pathPoint } from "../ui/src/magnifier/run.js";

const [url, name, shot, ...rest] = process.argv.slice(2);
const options = Object.fromEntries(
  rest.map((arg) => {
    const [key, value] = arg.replace(/^--/, "").split("=");
    return [key, value ?? true];
  }),
);
const playwrightRuns = Number(options["playwright-runs"] ?? 3);
const realRuns = Number(options["real-runs"] ?? 0);
const engines = { chromium, firefox };

if (options.headed && !options.exe) throw new Error("--headed needs --exe (the windows.py gate)");
const browser = await engines[name].launch({ headless: !options.headed, executablePath: options.exe });
const version = browser.version();
const records = [];
const waiters = [];

function emit(record) {
  process.stdout.write(`${JSON.stringify({ engine: name, version, headed: Boolean(options.headed), ...record })}\n`);
}

function take(record) {
  records.push(record);
  emit(record);
  for (const waiter of [...waiters]) {
    if (waiter.match(record)) {
      waiters.splice(waiters.indexOf(waiter), 1);
      waiter.resolve(record);
    }
  }
}

function waitFor(match, ms) {
  const found = records.find(match);
  if (found) return Promise.resolve(found);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      waiters.splice(waiters.indexOf(waiter), 1);
      reject(new Error(`timeout after ${ms} ms`));
    }, ms);
    const waiter = {
      match,
      resolve: (record) => {
        clearTimeout(timer);
        resolve(record);
      },
    };
    waiters.push(waiter);
  });
}

const isRun = (label, index) => (r) => r.type === "run" && r.label === label && r.index === index;
const isArmed = (next) => (r) => r.type === "armed" && r.next === next;

try {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.exposeFunction("spikeLogSink", (record) => take(record));
  page.on("pageerror", (error) => emit({ type: "page_error", error: String(error) }));
  await page.goto(url);
  const ready = await waitFor((r) => r.type === "ready" || r.type === "failed", 120000);
  if (ready.type === "failed") throw new Error(ready.error);
  const [x, y, width, height] = ready.layout.main;
  let index = 0;
  await waitFor(isArmed(1), 120000);
  await page.evaluate(() => window.spikeMagnifier.label("playwright"));
  for (let run = 0; run < playwrightRuns; run += 1) {
    index += 1;
    await waitFor(isArmed(index), 30000);
    const started = performance.now();
    let calls = 0;
    let done = false;
    const finished = waitFor(isRun("playwright", index), 60000).then(() => (done = true));
    while (!done) {
      const elapsed = performance.now() - started;
      const point = pathPoint(elapsed, width, height);
      await page.mouse.move(x + point.x, y + point.y);
      calls += 1;
      const next = started + calls * PATH.eventEvery;
      const wait = next - performance.now();
      if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
    }
    await finished;
    emit({ type: "playwright_moves", index, calls, ms: performance.now() - started });
    // Away from the frame, so that the page re-arms.
    await page.mouse.move(x + width + 10, y + height + 40);
  }
  if (realRuns > 0) {
    await page.evaluate(() => window.spikeMagnifier.label("real"));
    await waitFor(isArmed(index + 1), 30000);
    emit({ type: "await_real", next: index + 1, runs: realRuns });
    for (let run = 0; run < realRuns; run += 1) {
      index += 1;
      await waitFor(isRun("real", index), 120000);
    }
  }
  await page.screenshot({ path: shot });
  emit({ type: "screenshot", path: shot });
} finally {
  await browser.close();
}
