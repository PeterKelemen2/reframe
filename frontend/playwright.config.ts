import { defineConfig, devices } from '@playwright/test'

import { projectServers, webServers } from './e2e/support/servers'

// Headless only, in every project: a headed browser or the UI mode would open windows on the
// owner's displays (docs/m4-breakdown.md, "Displays, windows and the pointer"). The list
// reporter prints to the terminal; the HTML reporter is left out because it opens a browser
// when a test fails.
const headless = true

const servers = projectServers(['chromium', 'firefox'])

export default defineConfig({
  testDir: './e2e',
  outputDir: './e2e/.results',
  forbidOnly: true,
  // A flaky flow must fail, not pass on a second try.
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [['list']],
  use: {
    headless,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  // Each project has its own server; its tests take turns on it (e2e/support/test.ts).
  webServer: webServers(servers),
  projects: [
    {
      name: 'chromium',
      workers: 1,
      use: { ...devices['Desktop Chrome'], headless, baseURL: servers.chromium },
    },
    {
      name: 'firefox',
      workers: 1,
      use: { ...devices['Desktop Firefox'], headless, baseURL: servers.firefox },
    },
  ],
})
