import type { Page } from '@playwright/test'

import type { CapabilitySnapshot, SystemInfo } from '../../src/api/types'
import { TOKEN } from './servers'
import { expect } from './test'

const MISMATCH_REASON = 'NVIDIA driver too old: NVENC needs driver 610.00 or newer'

/**
 * The page sees a server that found no FFmpeg: `GET /api/system` answers with both tools
 * missing. The server itself keeps its tools, so the builds list is its real one.
 */
export async function withoutFfmpeg(page: Page): Promise<void> {
  await page.route(
    (url) => url.pathname === '/api/system',
    async (route) => {
      const answer = await route.fetch()
      const info = (await answer.json()) as SystemInfo
      for (const name of ['ffmpeg', 'ffprobe'] as const) {
        info.tools[name] = {
          ...info.tools[name],
          status: 'missing',
          origin: null,
          path: null,
          version: null,
          bundled: false,
          reason: `${name} was not found: no bundled build, nothing on PATH.`,
        }
      }
      await route.fulfill({ response: answer, json: info })
    },
  )
}

/**
 * The page sees `hevc_nvenc` unavailable because this FFmpeg build needs a newer NVIDIA
 * driver (`build_mismatch`), as the pinned build reports on a GeForce 10 card.
 */
export async function withBuildMismatch(page: Page): Promise<void> {
  await page.route(
    (url) => url.pathname === '/api/system/encoders',
    async (route) => {
      const answer = await route.fetch()
      const snapshot = (await answer.json()) as CapabilitySnapshot
      const encoders = snapshot.encoders ?? {}
      const status = encoders.hevc_nvenc
      if (status !== undefined) {
        encoders.hevc_nvenc = {
          ...status,
          state: 'unavailable',
          reason: MISMATCH_REASON,
          build_mismatch: true,
        }
      }
      await route.fulfill({ response: answer, json: { ...snapshot, encoders } })
    },
  )
}

/** Opens the app on the first-run screen and waits for the offered builds. */
export async function openFirstRun(page: Page): Promise<void> {
  await page.goto(`/#token=${TOKEN}`)
  await expect(page.locator('[data-screen="first-run"]')).toBeVisible()
  await expect(page.locator('[data-build="default"]')).toBeVisible()
}
