/**
 * The desktop smoke test: the release app (frozen sidecar, bundled tools) driven through
 * `tauri-driver`, as a user would use it, from the start to the quit.
 *
 * `REFRAME_SMOKE_APP` is the app's executable (default: the release build in
 * `$CARGO_TARGET_DIR`, else `src-tauri/target`). `tauri-driver` and the platform's WebDriver
 * (`WebKitWebDriver`, `msedgedriver`) must be on `PATH`; on Linux it needs a display.
 */
import { type ChildProcess, execFile, spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { copyFile, mkdir, mkdtemp, readdir, readFile, rm, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'
import { promisify } from 'node:util'
import { after, before, describe, it, type TestContext } from 'node:test'
import assert from 'node:assert/strict'

import {
  Builder,
  By,
  Capabilities,
  type WebDriver,
  type WebElement,
  until,
} from 'selenium-webdriver'

import {
  closeWindows,
  descendants,
  isInside,
  kill,
  listProcesses,
  procName,
  programName,
  type Proc,
  sameProcess,
  WINDOWS,
} from './processes.ts'

const DRIVER_PORT = 8770
const NATIVE_PORT = 8771
const REPO = resolve(import.meta.dirname, '../../..')
const FIXTURE = join(REPO, 'testdata/media/multitrack.mkv')
const FIXTURE_SIZE = '320×180'
// A software encoder: every runner has it.
const PRESET = { id: 'fast-720p30', name: 'Fast 720p30' }
// Well past the quit flow's 5 s wait for the server before it kills it.
const QUIT_TIMEOUT = 20_000
const SESSION_TIMEOUT = 60_000
const END_STATES = new Set(['failed', 'cancelled', 'interrupted'])

function appPath(): string {
  const given = process.env.REFRAME_SMOKE_APP
  if (given) return resolve(given)
  const target = process.env.CARGO_TARGET_DIR ?? join(REPO, 'desktop/src-tauri/target')
  return resolve(target, 'release', WINDOWS ? 'Reframe.exe' : 'reframe-desktop')
}

const app = appPath()
let work = ''
let fixture = ''
let dataDir = ''
let env: NodeJS.ProcessEnv = {}
let driverProcess: ChildProcess | undefined
let driver: WebDriver | undefined
let appProc: Proc | undefined
let sidecar: Proc | undefined
let outputPath = ''
let broken = ''

/** Runs a step only while the steps before it passed: each one needs the state they left. */
function step(name: string, body: () => Promise<void>): void {
  it(name, async (t: TestContext) => {
    if (broken) {
      t.skip(`after "${broken}" failed`)
      return
    }
    try {
      await body()
    } catch (error) {
      broken = name
      await diagnose()
      throw error
    }
  })
}

async function diagnose(): Promise<void> {
  const log = join(dataDir, 'logs', 'sidecar.log')
  if (existsSync(log)) {
    const lines = (await readFile(log, 'utf8')).trimEnd().split('\n')
    console.error(`--- the last lines of ${log}\n${lines.slice(-40).join('\n')}`)
  }
  const text = await driver
    ?.findElement(By.css('body'))
    .then((body) => body.getText())
    .catch(() => null)
  if (text) console.error(`--- the page's text\n${text.slice(0, 3000)}`)
}

async function waitFor(
  description: string,
  condition: () => Promise<boolean>,
  timeout: number,
  deadline = Date.now() + timeout,
): Promise<void> {
  if (await condition()) return
  if (Date.now() > deadline) assert.fail(`${description} (waited ${timeout / 1000} s)`)
  await sleep(250)
  return waitFor(description, condition, timeout, deadline)
}

function page(): WebDriver {
  assert.ok(driver, 'no WebDriver session')
  return driver
}

async function visible(css: string, message: string, timeout: number): Promise<WebElement> {
  const element = await page().wait(until.elementLocated(By.css(css)), timeout, message)
  await page().wait(until.elementIsVisible(element), timeout, message)
  return element
}

async function enabled(css: string, message: string, timeout: number): Promise<WebElement> {
  const element = await visible(css, message, timeout)
  await page().wait(until.elementIsEnabled(element), timeout, message)
  return element
}

/**
 * The text of the first match, also where the layout hides it (an ellipsis in a narrow panel),
 * which WebDriver's visible text leaves out.
 */
async function textContent(css: string): Promise<string> {
  const [element] = await page().findElements(By.css(css))
  return ((await element?.getAttribute('textContent')) ?? '').trim()
}

/** Every new process of this run below `tauri-driver`. */
async function started(): Promise<Proc[]> {
  assert.ok(driverProcess?.pid, 'tauri-driver is not running')
  return descendants(await listProcesses(), driverProcess.pid)
}

async function partFiles(): Promise<string[]> {
  return (await readdir(dirname(fixture))).filter((name) => name.includes('.part'))
}

describe('the desktop app', { concurrency: 1 }, () => {
  before(async () => {
    work = await mkdtemp(join(tmpdir(), 'reframe-smoke-'))
    dataDir = join(work, 'data')
    const media = join(work, 'media')
    await mkdir(media)
    fixture = join(media, basename(FIXTURE))
    assert.ok(existsSync(FIXTURE), `no ${FIXTURE}: run scripts/make-testdata.py`)
    await copyFile(FIXTURE, fixture)
    // Each folder the app, its server and its webview write to is this run's own; on Windows
    // msedgedriver gives WebView2 a profile of its own.
    env = {
      ...process.env,
      REFRAME_DATA_DIR: dataDir,
      REFRAME_CONFIG_DIR: join(work, 'config'),
      REFRAME_CACHE_DIR: join(work, 'cache'),
      REFRAME_POWER_DRY_RUN: '1',
    }
    if (!WINDOWS) {
      env.XDG_CONFIG_HOME = join(work, 'xdg-config')
      env.XDG_DATA_HOME = join(work, 'xdg-data')
      env.XDG_CACHE_HOME = join(work, 'xdg-cache')
    }
    driverProcess = spawn(
      'tauri-driver',
      ['--port', String(DRIVER_PORT), '--native-port', String(NATIVE_PORT)],
      { env, stdio: ['ignore', 'inherit', 'inherit'], windowsHide: true },
    )
    await waitFor(
      'tauri-driver answers',
      () =>
        fetch(`http://127.0.0.1:${DRIVER_PORT}/status`)
          .then((answer) => answer.ok)
          .catch(() => false),
      30_000,
    )
  })

  after(async () => {
    await driver?.quit().catch(() => undefined)
    // A failed step can leave the app running: end what this run started, then the driver.
    const left = driverProcess?.pid ? await started() : []
    const strays = (await listProcesses()).filter(
      (proc) => appProc !== undefined && proc.commandLine.includes(`--parent-pid ${appProc.pid}`),
    )
    await kill([...left, ...strays])
    driverProcess?.kill()
    if (work) await rm(work, { recursive: true, force: true, maxRetries: 10 })
  })

  step('starts', async () => {
    assert.ok(existsSync(app), `the app ${app} does not exist`)
    const capabilities = new Capabilities()
    capabilities.setBrowserName('wry')
    // msedgedriver passes each argument as a `--` switch, which the app ignores: on Windows the
    // file comes from a second launch.
    capabilities.set('tauri:options', { application: app, args: WINDOWS ? [] : [fixture] })
    const candidate = new Builder()
      .usingServer(`http://127.0.0.1:${DRIVER_PORT}/`)
      .withCapabilities(capabilities)
      .build()
    // WebKitWebDriver waits without end for an app that exits before its page loads.
    const session = candidate.getSession()
    session.catch(() => undefined)
    candidate.catch(() => undefined)
    const timer = new AbortController()
    try {
      const expired = sleep(SESSION_TIMEOUT, true, { signal: timer.signal }).catch(() => false)
      if ((await Promise.race([session, expired])) === true) {
        assert.fail(`the app opened no page within ${SESSION_TIMEOUT / 1000} s`)
      }
    } finally {
      timer.abort()
    }
    driver = candidate
    // WebView2's session can open before the page has loaded.
    await driver.wait(until.titleIs('Reframe'), 30_000, 'the page is not Reframe')
    const name = programName(app)
    appProc = (await started()).find((proc) => procName(proc) === name)
    assert.ok(appProc, `no ${name} process below tauri-driver`)
  })

  step('reaches its backend', async () => {
    const shown = await page().wait(
      async () => {
        const [screen] = await page().findElements(
          By.css('[data-connection="open"], .backend-error'),
        )
        return screen ?? false
      },
      60_000,
      'the page has no open connection',
    )
    assert.ok(shown)
    if ((await shown.getAttribute('class'))?.includes('backend-error')) {
      assert.fail(`the backend failed: ${await textContent('.backend-error')}`)
    }
    const all = await listProcesses()
    assert.ok(appProc)
    sidecar = descendants(all, appProc.pid).find(
      (proc) => proc.ppid === appProc?.pid && procName(proc) === 'reframe-server',
    )
    assert.ok(sidecar?.exe, 'the app started no reframe-server of its own')
  })

  step('shows the first-run screen with the bundled FFmpeg, and goes past it', async () => {
    assert.ok(sidecar?.exe)
    const resources = dirname(dirname(sidecar.exe))
    await visible('[data-screen="first-run"]', 'no first-run screen on a first start', 30_000)
    const path = await textContent('[data-tool="ffmpeg"] [data-field="path"]')
    assert.ok(isInside(path, resources), `ffmpeg ${path} is not the one bundled in ${resources}`)
    await (await enabled('.first-run__continue', 'no Continue button', 10_000)).click()
    await visible('.sources-panel', 'the workspace did not open', 10_000)
  })

  step('opens and probes the file given on its command line', async () => {
    if (WINDOWS) {
      // It hands the path to the running app and exits 0.
      await promisify(execFile)(app, [fixture], { env, timeout: 30_000 })
    }
    const message = `${fixture} from the command line is not in the sources`
    await page().wait(
      async () => {
        const items = await page().findElements(By.css('.source-item[data-path]'))
        const paths = await Promise.all(items.map((item) => item.getAttribute('data-path')))
        return paths.some((path) =>
          WINDOWS ? path?.toLowerCase() === fixture.toLowerCase() : path === fixture,
        )
      },
      30_000,
      message,
    )
    // The picture size comes from the probe. The panel may be too narrow to show the text, so
    // it is read from the DOM.
    await page().wait(
      async () => {
        const summaries = await page().findElements(By.css('.source-item [data-field="summary"]'))
        const texts = await Promise.all(summaries.map((item) => item.getAttribute('textContent')))
        return texts.some((text) => text?.includes(FIXTURE_SIZE))
      },
      30_000,
      `${fixture} was not probed (no ${FIXTURE_SIZE} in its summary)`,
    )
    await enabled('.preset-picker__trigger', 'the editor has no job for the file', 30_000)
  })

  step('queues a job and finishes it', async () => {
    await (await enabled('.preset-picker__trigger', 'no preset picker', 10_000)).click()
    await (
      await visible(`.preset-picker__list [data-preset="${PRESET.id}"]`, 'no preset', 10_000)
    ).click()
    await page().wait(
      async () =>
        (await textContent('.preset-picker__trigger [data-field="preset"]')) === PRESET.name,
      10_000,
      `the preset is not ${PRESET.name}`,
    )
    await (await enabled('.status-bar__add', 'the job cannot be added', 30_000)).click()
    await visible('[data-field="output-path"]', 'no output path', 10_000)
    outputPath = await textContent('[data-field="output-path"]')
    assert.equal(dirname(outputPath), dirname(fixture), 'the output is not next to the file')
    await (await enabled('.status-bar__start', 'the queue cannot be started', 30_000)).click()
    await (await visible('.status-bar__queue', 'no queue link', 10_000)).click()

    let state = ''
    await waitFor(
      'the job is done',
      async () => {
        const rows = await page().findElements(By.css('.queue-table__buttons[data-state]'))
        // The queue view fills its table after it opens.
        if (rows.length === 0) return false
        assert.equal(rows.length, 1, 'the queue should hold this one job')
        state = (await rows[0]!.getAttribute('data-state')) ?? ''
        assert.ok(!END_STATES.has(state), `the job ended ${state}`)
        return state === 'done'
      },
      120_000,
    )
    const output = await stat(outputPath).catch(() => null)
    assert.ok(output?.isFile() && output.size > 0, `the job's output ${outputPath} is missing`)
  })

  step('quits without leaving processes or files behind', async () => {
    assert.ok(appProc && sidecar)
    const running = await started()
    const live = running.find((proc) => sameProcess(proc, appProc!))
    assert.ok(live, 'the app ended before it was asked to quit')
    const tree = [live, ...descendants(running, live.pid)]
    const resources = dirname(dirname(sidecar.exe!))

    await closeWindows(live.pid)
    let left: Proc[] = []
    await waitFor(
      'the app and the processes it started end',
      async () => {
        const all = await listProcesses()
        left = all.filter(
          (proc) =>
            tree.some((own) => sameProcess(own, proc)) ||
            (proc.exe !== null && isInside(proc.exe, resources)) ||
            proc.commandLine.includes(`--parent-pid ${live.pid}`),
        )
        return left.length === 0
      },
      QUIT_TIMEOUT,
    ).catch(() => {
      const names = left.map((proc) => `${proc.pid} ${proc.exe ?? proc.name}`).join(', ')
      assert.fail(`still running ${QUIT_TIMEOUT / 1000} s after the quit: ${names}`)
    })

    assert.deepEqual(await partFiles(), [], 'a .part file is left next to the output')
    // Only the quit flow sends it: a killed app's server ends on a signal or a parent watch.
    const log = await readFile(join(dataDir, 'logs', 'sidecar.log'), 'utf8')
    assert.match(log, /"POST \/api\/system\/shutdown HTTP\/1\.1" 204/, 'no shutdown request')
  })
})
