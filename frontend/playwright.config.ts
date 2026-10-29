import { defineConfig, devices } from '@playwright/test'

// Headless only, in every project: a headed browser or the UI mode would open windows on the
// owner's displays (docs/m4-breakdown.md, "Displays, windows and the pointer"). The list
// reporter prints to the terminal; the HTML reporter is left out because it opens a browser
// when a test fails.
const headless = true

export default defineConfig({
  testDir: './e2e',
  outputDir: './e2e/.results',
  forbidOnly: true,
  reporter: [['list']],
  use: {
    headless,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], headless } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'], headless } },
  ],
})
