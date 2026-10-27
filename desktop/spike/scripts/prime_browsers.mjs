// The PrimeVue page in Playwright's Chromium and Firefox: every theme and state, a screenshot
// of each and the page's own measurements, as JSON lines on stdout.
// node scripts/prime_browsers.mjs <page url> <out dir> <width> <height>
//   [--engines=chromium,firefox] [--states=base,select,dialog] [--headed] [--suffix=-headed]
//   [--exe-<engine>=<path>]
// A headed run needs --exe-<engine>: the gate of windows.py (Session.wrapper), so that its
// window goes to the secondary output.
import { chromium, firefox } from "playwright";

const [url, out, width, height, ...rest] = process.argv.slice(2);
const options = Object.fromEntries(
  rest.map((arg) => {
    const [key, value] = arg.replace(/^--/, "").split("=");
    return [key, value ?? true];
  }),
);
const engines = { chromium, firefox };
const wanted = options.engines ? options.engines.split(",") : Object.keys(engines);
const suffix = options.suffix ?? "";
const states = options.states ? options.states.split(",") : ["base", "select", "dialog"];

for (const name of wanted) {
  const executablePath = options[`exe-${name}`];
  if (options.headed && !executablePath) throw new Error(`--headed needs --exe-${name}`);
  const browser = await engines[name].launch({ headless: !options.headed, executablePath });
  try {
    const context = await browser.newContext({
      viewport: { width: Number(width), height: Number(height) },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();
    const logs = [];
    await page.exposeFunction("spikeLogSink", (record) => logs.push(record));
    page.on("pageerror", (error) => logs.push({ check: "page", type: "error", error: String(error) }));
    await page.goto(url);
    await page.waitForFunction(() => window.spikePrime !== undefined, null, { timeout: 30000 });
    const engine = `${name}${suffix}`;
    const version = browser.version();
    for (const theme of ["light", "dark"]) {
      for (const state of states) {
        const metrics = await page.evaluate(([t, s]) => window.spikePrime.apply(t, s), [theme, state]);
        const path = `${out}/${engine}-${theme}-${state}.png`;
        await page.screenshot({ path });
        console.log(JSON.stringify({ engine, version, theme, state, metrics, path }));
      }
    }
    console.log(JSON.stringify({ engine, version, logs }));
  } finally {
    await browser.close();
  }
}
