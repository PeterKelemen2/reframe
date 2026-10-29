import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, problem } from '@/api/testing/fakes'

import { forgetThumbnails, LINK_REUSE_MS, useThumbnail } from './useThumbnail'

function frames(sourceId: string) {
  return {
    frames: [
      {
        key: `${sourceId}-2000-0`,
        kind: 'source',
        timestamp: 2,
        width: 320,
        height: 180,
        cached: false,
        url: `/api/preview/frames/${sourceId}-2000-0.png?exp=1&sig=s${Math.random()}`,
      },
    ],
    notes: [],
  }
}

describe('the source thumbnail', () => {
  let server: FakeServer
  const scopes: ReturnType<typeof effectScope>[] = []

  beforeEach(() => {
    forgetThumbnails()
    server = new FakeServer().on('POST /api/preview/frames', (request) =>
      frames((request.body as { source_id: string }).source_id),
    )
    configureClient({ baseUrl: 'http://server:8790', token: 't', fetch: server.fetch })
  })

  afterEach(() => {
    for (const scope of scopes.splice(0)) scope.stop()
    vi.useRealTimers()
  })

  function thumbnail(id: string | null, hasVideo = true) {
    const scope = effectScope()
    scopes.push(scope)
    const source = ref(id)
    const result = scope.run(() => useThumbnail(source, hasVideo))!
    return { ...result, source, scope }
  }

  function requests() {
    return server.requests.filter((request) => request.path === '/api/preview/frames')
  }

  it("asks for one frame of the source and gives its link on the server's address", async () => {
    const { url } = thumbnail('movie')
    await flushPromises()
    expect(requests().map((request) => request.body)).toEqual([{ source_id: 'movie', count: 1 }])
    expect(url.value).toMatch(/^http:\/\/server:8790\/api\/preview\/frames\/movie-2000-0\.png\?/)
  })

  it('takes the same link again for the same source, so the browser shows the image it has', async () => {
    const first = thumbnail('movie')
    await flushPromises()
    first.scope.stop()
    const second = thumbnail('movie')
    await flushPromises()
    expect(requests()).toHaveLength(1)
    expect(second.url.value).toBe(first.url.value)
  })

  it('asks again once a link is older than the browser keeps the image', async () => {
    vi.useFakeTimers()
    const first = thumbnail('movie')
    await vi.advanceTimersByTimeAsync(0)
    first.scope.stop()
    vi.setSystemTime(Date.now() + LINK_REUSE_MS + 1)
    thumbnail('movie')
    await vi.advanceTimersByTimeAsync(0)
    expect(requests()).toHaveLength(2)
  })

  it('asks for nothing for a source without video', async () => {
    const { url } = thumbnail('movie', false)
    await flushPromises()
    expect(requests()).toHaveLength(0)
    expect(url.value).toBeNull()
  })

  it('asks for a new link once when the image does not load, then gives up', async () => {
    const { url, failed } = thumbnail('movie')
    await flushPromises()
    const first = url.value
    failed()
    await flushPromises()
    expect(requests()).toHaveLength(2)
    expect(url.value).not.toBe(first)
    expect(url.value).not.toBeNull()
    failed()
    await flushPromises()
    expect(requests()).toHaveLength(2)
    expect(url.value).toBeNull()
  })

  it('shows no picture when no frame can be made', async () => {
    server.on('POST /api/preview/frames', () => problem(422, 'preview.failed', 'No frame'))
    const { url, loading } = thumbnail('movie')
    await flushPromises()
    expect(url.value).toBeNull()
    expect(loading.value).toBe(false)
  })

  it("never shows the last source's frame for the next source", async () => {
    const slow = deferred()
    server.on('POST /api/preview/frames', async (request) => {
      const id = (request.body as { source_id: string }).source_id
      if (id === 'slow') await slow.promise
      return frames(id)
    })
    const { url, source } = thumbnail('slow')
    await flushPromises()
    source.value = 'fast'
    await flushPromises()
    slow.resolve()
    await flushPromises()
    expect(url.value).toContain('/fast-2000-0.png')
  })
})
