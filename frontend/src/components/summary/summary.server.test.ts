import { createPinia, setActivePinia } from 'pinia'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'

import { configureClient } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import { pinnedTools } from '@/editor/testing/tools.mjs'
import { useEditorStore } from '@/stores/editor'

import { pipelineOf } from './pipeline'
import { useGeometry } from './useGeometry'
import { forgetThumbnails, useThumbnail } from './useThumbnail'

const PORT = 8791
const SOON = { timeout: 30_000, interval: 50 }

let server: DevServer
const ids: Record<string, string> = {}

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: ['--fixtures', 'multitrack,letterbox', ...(tools === null ? [] : ['--tools-dir', tools])],
  })
  const probe = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
    paths: [`${server.media}/multitrack.mkv`, `${server.media}/letterbox.mkv`],
  })
  const task = await endedTask(server, probe.task_id)
  for (const { id, path } of (task.result as { sources: { id: string; path: string }[] }).sources) {
    ids[path.split('/').at(-1) ?? path] = id
  }
}, 120_000)

afterAll(async () => {
  await server.stop()
})

beforeEach(() => {
  setActivePinia(createPinia())
  forgetThumbnails()
  configureClient({ baseUrl: server.url, token: server.token })
})

describe('the Summary against a real server', () => {
  it('shows the crop and scale that jobs/geometry computes, and a copied video', async () => {
    const editor = useEditorStore()
    await editor.open(ids['letterbox.mkv']!)
    const scope = effectScope()
    const geometry = scope.run(() => useGeometry())!
    editor.patch([
      {
        op: 'replace',
        path: '/dimensions/crop',
        value: { mode: 'manual', rect: { top: 22, bottom: 24, left: 0, right: 0 } },
      },
      { op: 'replace', path: '/dimensions/pixel_aspect', value: 'custom' },
      { op: 'replace', path: '/dimensions/custom_par', value: { num: 4, den: 3 } },
    ])
    await vi.waitFor(() => {
      expect(geometry.pending.value).toBe(false)
      expect(pipelineOf(geometry.answer.value!)).toMatchObject({
        kind: 'encoded',
        source: { width: 320, height: 180 },
        crop: { width: 320, height: 134 },
        scale: { width: 240, height: 134 },
        par: { num: 4, den: 3 },
      })
    }, SOON)
    editor.set('/video/passthrough', true)
    await vi.waitFor(() => {
      expect(geometry.pending.value).toBe(false)
      expect(pipelineOf(geometry.answer.value!)).toEqual({
        kind: 'copied',
        source: { width: 320, height: 180 },
      })
    }, SOON)
    scope.stop()
  })

  it('gives a frame link that loads as a PNG without the token, as an <img> asks for it', async () => {
    const scope = effectScope()
    const thumbnail = scope.run(() => useThumbnail(ids['multitrack.mkv']!, true))!
    await vi.waitFor(() => expect(thumbnail.url.value).not.toBeNull(), SOON)
    expect(thumbnail.url.value!.startsWith(`${server.url}/api/preview/frames/`)).toBe(true)
    const image = await fetch(thumbnail.url.value!)
    expect(image.status).toBe(200)
    expect(image.headers.get('content-type')).toBe('image/png')
    const signature = new URL(thumbnail.url.value!)
    signature.searchParams.set('sig', 'forged')
    expect((await fetch(signature)).status).toBe(401)
    scope.stop()
  })
})
