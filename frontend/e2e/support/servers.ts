import { delimiter } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { PlaywrightTestConfig } from '@playwright/test'

import { pinnedTools } from '../../src/editor/testing/tools.mjs'

/** The page reads it from `#token=…`; the server is started with it. */
export const TOKEN = 'reframe-e2e-token'

const E2E = fileURLToPath(new URL('../', import.meta.url))
const DEV_SERVER = fileURLToPath(new URL('../../../scripts/dev-server.py', import.meta.url))
// Hardware test encodes fail with a captured real error; every other call runs the real tools,
// so the encoder states are the same on every machine.
const SCENARIO = `${E2E}fake-ffmpeg.json`
// Hardware test encodes on: without them a hardware encoder is only "not tested".
const SETTINGS = `${E2E}settings.json`
const FIRST_PORT = 8750
// Longer than dev-server.py's own stop (10 s), so the home is removed before Playwright's
// SIGKILL. Shorter than Playwright's 30 s exit.
const STOP_TIMEOUT = 20_000

/**
 * The base URL of each browser project's own server, so that one project's queue never shows in
 * the other's.
 */
export function projectServers<P extends string>(projects: readonly P[]): Record<P, string> {
  return Object.fromEntries(
    projects.map((project, index) => [project, `http://127.0.0.1:${FIRST_PORT + index}`]),
  ) as Record<P, string>
}

function quote(value: string): string {
  return `'${value.replaceAll("'", `'"'"'`)}'`
}

/** The PATH of the servers: the pinned FFmpeg first when there is one, for the fake's `exec`. */
function toolsPath(): Record<string, string> {
  const tools = pinnedTools()
  if (tools === null) return {}
  return { PATH: [tools, process.env.PATH].filter(Boolean).join(delimiter) }
}

/**
 * The `webServer` entries: `scripts/dev-server.py` for each project. Playwright starts them one
 * after the other, so the first one builds `dist/` for all.
 */
export function webServers(
  servers: Record<string, string>,
): NonNullable<PlaywrightTestConfig['webServer']> {
  return Object.entries(servers).map(([project, baseURL], index) => {
    const start = [
      'uv run python',
      quote(DEV_SERVER),
      `--port ${new URL(baseURL).port}`,
      `--token ${TOKEN}`,
      '--fixtures multitrack',
      // Makes the output root a media root too, so a flow can probe its job's output.
      '--output-fixtures chapters',
      `--fake-ffmpeg ${quote(SCENARIO)}`,
      `--settings ${quote(SETTINGS)}`,
    ].join(' ')
    return {
      name: project,
      command: index === 0 ? `npm run build:web && ${start}` : start,
      url: `${baseURL}/api/health`,
      env: toolsPath(),
      reuseExistingServer: false,
      timeout: 120_000,
      gracefulShutdown: { signal: 'SIGTERM', timeout: STOP_TIMEOUT },
      // The server logs every request; DEBUG=pw:webserver shows its output.
      stdout: 'ignore',
      stderr: 'ignore',
    }
  })
}
