import { expect, type APIRequestContext, type Page } from '@playwright/test'

import type { AppSettings, JsonPatchOp, MediaSource, QueueJob, TaskInfo } from '../../src/api/types'
import { TOKEN } from './servers'

const AUTH = { Authorization: `Bearer ${TOKEN}` }

/** Opens the app with the run's token in the address fragment and waits for the workspace. */
export async function openApp(page: Page): Promise<void> {
  await page.goto(`/#token=${TOKEN}`)
  await expect(page.locator('.sources-panel')).toBeVisible()
}

/**
 * Opens a file through `Ctrl+O` and the file browser, and waits for its job. The file is in the
 * media root, or in the root named `root` (`output` for an `--output-fixtures` file).
 */
export async function openFile(page: Page, name: string, root?: string): Promise<void> {
  await page.keyboard.press('ControlOrMeta+O')
  const dialog = page.locator('.file-browser-dialog')
  await expect(dialog).toBeVisible()
  if (root !== undefined) {
    const named = page.locator('.file-browser__root-name').getByText(root, { exact: true })
    await dialog.locator('[data-role="root"]', { has: named }).first().click()
  }
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

/** The server's settings, read with the run's token. */
export async function readSettings(request: APIRequestContext): Promise<AppSettings> {
  const answer = await request.get('/api/settings', { headers: AUTH })
  expect(answer.ok()).toBe(true)
  return (await answer.json()) as AppSettings
}

/** Changes the server's settings and checks the answer. */
export async function changeSettings(
  request: APIRequestContext,
  ops: JsonPatchOp[],
): Promise<void> {
  const answer = await request.put('/api/settings', { headers: AUTH, data: ops })
  expect(answer.ok(), `PUT /api/settings: ${answer.status()}`).toBe(true)
}

/** Probes a file through the server and gives what the server read from it. */
export async function probeFile(request: APIRequestContext, path: string): Promise<MediaSource> {
  const accepted = await request.post('/api/sources', {
    headers: AUTH,
    data: { paths: [path], recursive: false },
  })
  expect(accepted.ok(), `POST /api/sources: ${accepted.status()}`).toBe(true)
  const { task_id: taskId } = (await accepted.json()) as { task_id: string }
  const task = async (): Promise<TaskInfo> => {
    const answer = await request.get(`/api/tasks/${taskId}`, { headers: AUTH })
    expect(answer.ok()).toBe(true)
    return (await answer.json()) as TaskInfo
  }
  await expect
    .poll(async () => (await task()).state, { message: `probe of ${path}` })
    .not.toMatch(/^(queued|running)$/)
  const ended = await task()
  expect(ended.state, ended.error ?? undefined).toBe('done')
  const summary = ended.result as { sources: { id: string; path: string }[] }
  const id = summary.sources.find((source) => source.path === path)?.id
  expect(id, `a source for ${path}`).toBeDefined()
  const answer = await request.get(`/api/sources/${id}`, { headers: AUTH })
  expect(answer.ok()).toBe(true)
  return (await answer.json()) as MediaSource
}

/** Sends a queue action and checks its answer. */
export async function queueAction(
  request: APIRequestContext,
  method: 'post' | 'delete',
  path: string,
): Promise<void> {
  const answer = await request[method](path, { headers: AUTH })
  expect(answer.ok(), `${method.toUpperCase()} ${path}: ${answer.status()}`).toBe(true)
}
