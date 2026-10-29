import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { ApiError, configureClient } from '@/api/client'
import { deferred, FakeServer, problem } from '@/api/testing/fakes'
import type { AppSettings, JsonPatchOp } from '@/api/types'

import { hasPointer, useSettingsStore } from './settings'
import { useToastStore } from './toasts'

function settings(whenDone: string, extra: Record<string, unknown> = {}): AppSettings {
  return {
    schema_version: 1,
    queue: { when_done: whenDone, parallel_jobs: 1, sleep_inhibit: true, notifications: true },
    ...extra,
  } as AppSettings
}

describe('the settings store', () => {
  let server: FakeServer

  beforeEach(() => {
    setActivePinia(createPinia())
    server = new FakeServer().on('GET /api/settings', settings('nothing'))
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  })

  it('loads the settings', async () => {
    const store = useSettingsStore()
    await store.load()
    expect(store.loaded).toBe(true)
    expect(store.settings?.queue?.when_done).toBe('nothing')
  })

  it('sends a patch and keeps the answer', async () => {
    server.on('PUT /api/settings', () => ({
      settings: settings('sleep'),
      changes: [],
      saved: true,
      warnings: [],
    }))
    const store = useSettingsStore()
    const ops: JsonPatchOp[] = [{ op: 'replace', path: '/queue/when_done', value: 'sleep' }]
    const change = await store.update(ops)
    expect(change.saved).toBe(true)
    expect(store.settings?.queue?.when_done).toBe('sleep')
    expect(server.requests.at(-1)?.body).toEqual(ops)
  })

  it('rejects a refused patch with its problem and shows no toast', async () => {
    server.on('PUT /api/settings', () => problem(422, 'settings.invalid', 'Not a render node'))
    const store = useSettingsStore()
    await store.load()
    const refused = store.update([{ op: 'replace', path: '/encoders/vaapi_device', value: '/x' }])
    await expect(refused).rejects.toBeInstanceOf(ApiError)
    await expect(refused).rejects.toMatchObject({
      status: 422,
      problem: { code: 'settings.invalid' },
    })
    expect(useToastStore().items).toEqual([])
    expect(store.settings?.queue?.when_done).toBe('nothing')
  })

  it('sets a member with replace, or add where it is missing', async () => {
    server.on('PUT /api/settings', () => ({
      settings: settings('x'),
      changes: [],
      saved: true,
      warnings: [],
    }))
    const store = useSettingsStore()
    await store.load()
    await store.set('/queue/when_done', 'notify')
    await store.set('/output/default_folder', '/out')
    const sent = server.requests.filter((r) => r.method === 'PUT').map((r) => r.body)
    expect(sent).toEqual([
      [{ op: 'replace', path: '/queue/when_done', value: 'notify' }],
      [{ op: 'add', path: '/output/default_folder', value: '/out' }],
    ])
  })

  it('sends one patch at a time, so answers apply in order', async () => {
    const first = deferred<Response>()
    let calls = 0
    server.on('PUT /api/settings', () => {
      calls += 1
      if (calls === 1) return first.promise
      return { settings: settings('second'), changes: [], saved: true, warnings: [] }
    })
    const store = useSettingsStore()
    const one = store.update([{ op: 'replace', path: '/queue/when_done', value: 'first' }])
    const two = store.update([{ op: 'replace', path: '/queue/when_done', value: 'second' }])
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(calls).toBe(1)
    first.resolve(
      new Response(
        JSON.stringify({ settings: settings('first'), changes: [], saved: true, warnings: [] }),
        {
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    await Promise.all([one, two])
    expect(store.settings?.queue?.when_done).toBe('second')
  })

  it('finds a member by its JSON pointer, escapes included', () => {
    const document = { 'a/b': { '~c': 0 }, list: [1] }
    expect(hasPointer(document, '/a~1b/~0c')).toBe(true)
    expect(hasPointer(document, '/list/0')).toBe(true)
    expect(hasPointer(document, '/list/1')).toBe(false)
    expect(hasPointer(document, '/missing/x')).toBe(false)
    expect(hasPointer(null, '/x')).toBe(false)
  })
})
