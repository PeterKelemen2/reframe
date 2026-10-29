import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useToastStore } from '@/stores/toasts'

import { api, apiQuiet, ApiError, configureClient, onUnauthorized, unwrap } from './client'
import { FakeServer, problem } from './testing/fakes'

const path = { params: { path: { job_id: 'gone' } } }

function caught(run: () => unknown): unknown {
  try {
    run()
  } catch (error) {
    return error
  }
  return undefined
}

describe('the API client', () => {
  let server: FakeServer

  beforeEach(() => {
    setActivePinia(createPinia())
    server = new FakeServer()
    configureClient({ baseUrl: 'http://server:8765', token: null, fetch: server.fetch })
  })

  it('shows a problem answer of api as a toast with its title and detail', async () => {
    server.on('GET /api/queue/gone/log', () =>
      problem(404, 'queue.unknown_job', 'No job gone', 'It was removed.'),
    )
    const result = await api.GET('/api/queue/{job_id}/log', path)
    const error = caught(() => unwrap(result))

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, problem: { code: 'queue.unknown_job' } })
    expect(useToastStore().items).toEqual([
      expect.objectContaining({
        severity: 'error',
        summary: 'No job gone',
        detail: 'It was removed.',
      }),
    ])
  })

  it('shows no toast for a problem answer of apiQuiet', async () => {
    server.on('GET /api/queue/gone/log', () => problem(404, 'queue.unknown_job', 'No job gone'))
    const result = await apiQuiet.GET('/api/queue/{job_id}/log', path)
    expect(caught(() => unwrap(result))).toBeInstanceOf(ApiError)
    expect(useToastStore().items).toEqual([])
  })

  it('names an answer that is not a problem by its status', async () => {
    server.on('GET /api/queue', () => new Response('<html>Bad gateway</html>', { status: 502 }))
    const error = caught(() => unwrap({ response: new Response(null, { status: 502 }) }))
    await api.GET('/api/queue')

    expect(error).toMatchObject({ status: 502, problem: { code: 'http.502' } })
    expect(useToastStore().items[0]?.summary).toBe('The server answered with an error (502)')
  })

  it('turns a failed request into an ApiError with status 0, toasted once while it shows', async () => {
    configureClient({ fetch: () => Promise.reject(new TypeError('fetch failed')) })
    const first = api.GET('/api/queue')
    await expect(first).rejects.toBeInstanceOf(ApiError)
    await expect(first).rejects.toMatchObject({ status: 0, problem: { code: 'network' } })
    await expect(api.GET('/api/queue')).rejects.toBeInstanceOf(ApiError)
    const toasts = useToastStore()
    expect(toasts.items).toHaveLength(1)

    toasts.dismiss(toasts.items[0]?.id ?? 0)
    await expect(api.GET('/api/queue')).rejects.toBeInstanceOf(ApiError)
    expect(toasts.items).toHaveLength(1)
  })

  it('shows no toast for a failed request of apiQuiet', async () => {
    configureClient({ fetch: () => Promise.reject(new TypeError('fetch failed')) })
    await expect(apiQuiet.GET('/api/queue')).rejects.toMatchObject({ status: 0 })
    expect(useToastStore().items).toEqual([])
  })

  it('sends the token as a bearer token, and a header the caller set instead', async () => {
    server.on('GET /api/queue', { jobs: [] })
    server.on('GET /api/auth/status', { mode: 'token', authenticated: true })
    configureClient({ token: 'tab-token' })
    await api.GET('/api/queue')
    await apiQuiet.GET('/api/auth/status', { headers: { Authorization: 'Bearer typed' } })
    configureClient({ token: null })
    await api.GET('/api/queue')

    const sent = server.requests.map((request) => request.headers.get('Authorization'))
    expect(sent).toEqual(['Bearer tab-token', 'Bearer typed', null])
    expect(server.requests[0]?.path).toBe('/api/queue')
  })

  it('tells the listeners about a 401 of either client and does not toast it', async () => {
    server.on('GET /api/queue', () => problem(401, 'auth.invalid', 'The credentials are not valid'))
    const listener = vi.fn<() => void>()
    const stop = onUnauthorized(listener)
    await api.GET('/api/queue')
    await apiQuiet.GET('/api/queue')
    stop()
    await api.GET('/api/queue')

    expect(listener).toHaveBeenCalledTimes(2)
    expect(useToastStore().items).toEqual([])
  })
})
