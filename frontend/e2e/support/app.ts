import { expect, type APIRequestContext, type Page } from '@playwright/test'

import type { QueueJob } from '../../src/api/types'
import { TOKEN } from './servers'

const AUTH = { Authorization: `Bearer ${TOKEN}` }

/** Opens the app with the run's token in the address fragment and waits for the workspace. */
export async function openApp(page: Page): Promise<void> {
  await page.goto(`/#token=${TOKEN}`)
  await expect(page.locator('.sources-panel')).toBeVisible()
}

/** Opens a file of the media root through `Ctrl+O` and the file browser, and waits for its job. */
export async function openFile(page: Page, name: string): Promise<void> {
  await page.keyboard.press('ControlOrMeta+O')
  const dialog = page.locator('.file-browser-dialog')
  await expect(dialog).toBeVisible()
  await dialog.locator(`.file-browser__entry[data-name="${name}"]`).click()
  await dialog.locator('[data-action="confirm"]').click()
  await expect(dialog).toBeHidden()
  // The picker is enabled once the editor has the source's job.
  await expect(page.locator('.preset-picker__trigger')).toBeEnabled()
}

/**
 * Waits until a value of one of the app's Pinia stores equals `expected` (`path`: `presetId`,
 * `job.video.encoder`). For waiting on state only; the flows act through the UI.
 */
export async function waitForStore(
  page: Page,
  store: string,
  path: string,
  expected: string | number | boolean | null,
): Promise<void> {
  const read = () =>
    // A function, not a string: the app's CSP forbids the eval a string would need.
    page.evaluate(
      (wanted) => {
        // This file is type-checked without the DOM library.
        const doc = Reflect.get(globalThis, 'document') as { querySelector(s: string): unknown }
        const pinia = ['__vue_app__', 'config', 'globalProperties', '$pinia', '_s']
        let value = doc.querySelector('#app')
        for (const key of [...pinia, wanted.store, ...wanted.path.split('.')]) {
          if (value instanceof Map) value = value.get(key)
          else if (typeof value === 'object' && value !== null) value = Reflect.get(value, key)
          else return undefined
        }
        return value
      },
      { store, path },
    )
  await expect.poll(read, { message: `${store}.${path}` }).toBe(expected)
}

export interface QueueSnapshot {
  jobs: QueueJob[]
  processing: boolean
}

/** The server's queue, read with the run's token. */
export async function readQueue(request: APIRequestContext): Promise<QueueSnapshot> {
  const answer = await request.get('/api/queue', { headers: AUTH })
  expect(answer.ok()).toBe(true)
  return (await answer.json()) as QueueSnapshot
}

/** Sends a queue action (`/api/queue/stop`, `/api/queue/{id}/cancel`, …) and checks its answer. */
export async function queueAction(
  request: APIRequestContext,
  method: 'post' | 'delete',
  path: string,
): Promise<void> {
  const answer = await request[method](path, { headers: AUTH })
  expect(answer.ok(), `${method.toUpperCase()} ${path}: ${answer.status()}`).toBe(true)
}
