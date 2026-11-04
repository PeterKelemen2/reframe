import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useQueueStore } from '@/stores/queue'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

import type { DesktopBackend, DesktopBackendState, DesktopShell } from '@/platform/types'

import { boot, desktopBackend, shutdown } from './boot'
import { api, clientBaseUrl, clientToken } from './client'
import { FakeServer, FakeSocket, problem } from './testing/fakes'
import type { AuthStatus } from './types'

const FAST = { initial: 10, max: 40, factor: 2 }

async function until(check: () => boolean): Promise<void> {
  await vi.waitFor(() => expect(check()).toBe(true), { timeout: 2_000, interval: 5 })
}

describe('boot', () => {
  let server: FakeServer
  let sockets: FakeSocket[]
  let status: AuthStatus

  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    sockets = []
    status = { mode: 'token', authenticated: true }
    server = new FakeServer()
      .on('GET /api/auth/status', ({ headers }) => ({
        ...status,
        authenticated: status.authenticated && headers.get('Authorization') !== 'Bearer stale',
      }))
      .on('GET /api/definitions', { definitions: {}, naming_variables: [] })
      .on('GET /api/languages', { languages: [] })
      .on('GET /api/system', {
        mode: 'web',
        auth: 'token',
        platform: 'linux',
        tools: {},
        problems: [],
      })
      .on('GET /api/system/encoders', { encoders: {}, detecting: false, from_cache: false })
      .on('GET /api/tasks', [])
      .on('GET /api/queue', { jobs: [] })
      .on('GET /api/power', { pending: null })
      .on('GET /api/settings', { schema_version: 1 })
  })

  afterEach(() => {
    shutdown()
  })

  function start(options: { token?: string | null; helloWait?: number } = {}): Promise<void> {
    return boot({
      backend: async () => ({ baseUrl: 'http://server:8765' }),
      token: options.token === undefined ? 'tab' : options.token,
      fetch: server.fetch,
      socket: (url) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
      helloWait: options.helloWait ?? 2_000,
      offlineBackoff: FAST,
      random: () => 0,
      connection: { backoff: FAST },
    })
  }

  /** Boots, answers the first socket's hello, and waits until the app is ready. */
  async function ready(instance = 'run-1'): Promise<FakeSocket> {
    const booting = start()
    await until(() => sockets.length === 1)
    const socket = sockets[0] as FakeSocket
    socket.open()
    socket.hello(instance)
    await booting
    expect(useSystemStore().phase).toBe('ready')
    return socket
  }

  it('shows the login when the server wants credentials, and forgets a token it refuses', async () => {
    sessionStorage.setItem('reframe.token', 'stale')
    status = { mode: 'token', authenticated: false }
    await start({ token: 'stale' })
    const system = useSystemStore()
    expect(system.phase).toBe('login')
    expect(system.auth).toEqual({ mode: 'token', authenticated: false })
    expect(clientToken()).toBeNull()
    expect(sessionStorage.getItem('reframe.token')).toBeNull()
    expect(sockets).toEqual([])
  })

  it('is offline while the server cannot be reached, and goes on when it answers', async () => {
    let failures = 2
    const answer = server.fetch
    const phases: string[] = []
    const booting = boot({
      backend: async () => ({ baseUrl: 'http://server:8765' }),
      token: 'tab',
      fetch: (input, init) => {
        phases.push(useSystemStore().phase)
        if (failures > 0) {
          failures -= 1
          return Promise.reject(new TypeError('fetch failed'))
        }
        return answer(input, init)
      },
      socket: (url) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        queueMicrotask(() => {
          socket.open()
          socket.hello()
        })
        return socket
      },
      offlineBackoff: FAST,
      random: () => 0,
    })
    await booting
    expect(phases.slice(0, 3)).toEqual(['booting', 'offline', 'offline'])
    expect(useSystemStore().phase).toBe('ready')
  })

  it('opens the event connection with the token, and reads the snapshots after its hello', async () => {
    const booting = start()
    await until(() => sockets.length === 1)
    const socket = sockets[0] as FakeSocket
    expect(socket.url).toBe('ws://server:8765/api/events')
    socket.open()
    expect(socket.sent).toEqual([JSON.stringify({ type: 'auth', token: 'tab' })])
    expect(server.count('GET /api/queue')).toBe(0)

    socket.hello()
    await booting
    expect(server.count('GET /api/queue')).toBe(1)
    expect(server.count('GET /api/tasks')).toBe(1)
    expect(server.count('GET /api/system/encoders')).toBe(1)
    expect(useQueueStore().loaded).toBe(true)
    expect(useSystemStore().connection).toBe('open')
  })

  it('reads the snapshots without the hello when it does not come in time, and again after it', async () => {
    const booting = start({ helloWait: 20 })
    await until(() => sockets.length === 1)
    await booting
    expect(useSystemStore().phase).toBe('ready')
    expect(server.count('GET /api/queue')).toBe(1)

    const socket = sockets[0] as FakeSocket
    socket.open()
    socket.hello()
    await until(() => server.count('GET /api/queue') === 2)
  })

  it('reads the snapshots again after a reconnect and after a gap', async () => {
    const socket = await ready()
    socket.end(1006)
    await until(() => sockets.length === 2)
    const again = sockets[1] as FakeSocket
    again.open()
    again.hello()
    await until(() => server.count('GET /api/queue') === 2)
    expect(server.count('GET /api/tasks')).toBe(2)
    expect(server.count('GET /api/system')).toBe(2)

    again.receive({ type: 'event', seq: 1, event: { type: 'queue.changed', job_ids: [] } })
    again.receive({ type: 'event', seq: 3, event: { type: 'queue.changed', job_ids: [] } })
    await until(() => server.count('GET /api/queue') === 3)
  })

  it('re-probes the sources after a hello from another server run only', async () => {
    const restarted = vi.spyOn(useSourcesStore(), 'onServerRestart').mockResolvedValue()
    const socket = await ready('run-1')
    socket.end(1012)
    await until(() => sockets.length === 2)
    sockets[1]?.open()
    sockets[1]?.hello('run-1')
    await until(() => server.count('GET /api/queue') === 2)
    expect(restarted).not.toHaveBeenCalled()

    sockets[1]?.end(1012)
    await until(() => sockets.length === 3)
    sockets[2]?.open()
    sockets[2]?.hello('run-2')
    expect(restarted).toHaveBeenCalledTimes(1)
    expect(useSystemStore().instance).toBe('run-2')
    await until(() => server.count('GET /api/definitions') === 2)
  })

  it('goes to the login on a 401 answer and closes the event connection', async () => {
    const socket = await ready()
    server.on('GET /api/queue', () => problem(401, 'auth.invalid', 'The credentials are not valid'))
    await api.GET('/api/queue')
    const system = useSystemStore()
    expect(system.phase).toBe('login')
    expect(system.auth?.authenticated).toBe(false)
    expect(system.connection).toBe('closed')
    expect(socket.closedWith).toBe(1000)
  })

  it('goes to the login on a 4401 close, and starts again after a login with new credentials', async () => {
    const socket = await ready()
    socket.end(4401)
    const system = useSystemStore()
    expect(system.phase).toBe('login')
    expect(system.connection).toBe('unauthorized')
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(sockets).toHaveLength(1)

    expect(await system.loginWithToken('fresh')).toBe(true)
    await until(() => sockets.length === 2)
    const next = sockets[1] as FakeSocket
    next.open()
    expect(next.sent).toEqual([JSON.stringify({ type: 'auth', token: 'fresh' })])
    next.hello()
    await until(() => system.phase === 'ready')
    expect(system.connection).toBe('open')
  })

  function startDesktop(shell: DesktopShell, reconnect = FAST): Promise<void> {
    return boot({
      desktop: shell,
      backend: () => Promise.reject(new Error('the web backend is not asked')),
      fetch: server.fetch,
      socket: (url) => {
        const socket = new FakeSocket(url)
        sockets.push(socket)
        return socket
      },
      helloWait: 2_000,
      offlineBackoff: FAST,
      random: () => 0,
      connection: { backoff: reconnect },
    })
  }

  describe('in the desktop app', () => {
    const sidecar: DesktopBackend = {
      baseUrl: 'http://127.0.0.1:8731',
      token: 'side',
      instance: 'run-1',
      owned: true,
      privateQueue: null,
    }
    let listeners: ((state: DesktopBackendState) => void)[]

    /** The shell's side: `backendInfo` answers with `info`, `send` is a `backend-state` event. */
    function desktopShell(info: () => Promise<DesktopBackend>): DesktopShell {
      listeners = []
      return {
        backendInfo: info,
        onBackendState(cb) {
          listeners.push(cb)
          return () => (listeners = listeners.filter((listener) => listener !== cb))
        },
      } as Partial<DesktopShell> as DesktopShell
    }

    function send(state: DesktopBackendState): void {
      for (const listener of listeners) listener(state)
    }

    async function readyDesktop(reconnect = FAST): Promise<FakeSocket> {
      const booting = startDesktop(
        desktopShell(async () => sidecar),
        reconnect,
      )
      await until(() => sockets.length === 1)
      sockets[0]?.open()
      sockets[0]?.hello('run-1')
      await booting
      return sockets[0] as FakeSocket
    }

    afterEach(() => {
      desktopBackend.value = null
    })

    it('connects to the shell’s backend with its token, and keeps no token in the tab', async () => {
      const socket = await readyDesktop()
      expect(socket.url).toBe('ws://127.0.0.1:8731/api/events')
      expect(socket.sent).toEqual([JSON.stringify({ type: 'auth', token: 'side' })])
      expect(server.requests.at(-1)?.headers.get('Authorization')).toBe('Bearer side')
      expect(sessionStorage.getItem('reframe.token')).toBeNull()
      expect(desktopBackend.value).toEqual({ state: 'ready', info: sidecar })
      expect(useSystemStore().phase).toBe('ready')
    })

    it('shows the failure of the first start, and goes on when a Retry makes it ready', async () => {
      const error = { message: 'No ready line within 20 s', log: '/d/logs/sidecar.log' }
      const booting = startDesktop(desktopShell(() => Promise.reject(error)))
      await until(() => desktopBackend.value?.state === 'failed')
      expect(desktopBackend.value).toEqual({ state: 'failed', error })
      expect(useSystemStore().phase).toBe('booting')
      expect(sockets).toEqual([])

      send({ state: 'starting' })
      expect(desktopBackend.value).toEqual({ state: 'starting' })
      send({ state: 'ready', info: sidecar })
      await until(() => sockets.length === 1)
      sockets[0]?.open()
      sockets[0]?.hello()
      await booting
      expect(useSystemStore().phase).toBe('ready')
      expect(desktopBackend.value).toEqual({ state: 'ready', info: sidecar })
    })

    it('connects to a restarted backend’s new address at once, and reads the queue there', async () => {
      // A reconnect of its own would wait a minute: only the new address can bring the socket.
      const first = await readyDesktop({ initial: 60_000, max: 60_000, factor: 1 })
      first.end(1006)
      send({ state: 'starting' })
      expect(desktopBackend.value).toEqual({ state: 'starting' })
      expect(sockets).toHaveLength(1)

      const restarted = {
        ...sidecar,
        baseUrl: 'http://127.0.0.1:8732',
        token: 'new',
        instance: 'run-2',
      }
      send({ state: 'ready', info: restarted })
      expect(clientBaseUrl()).toBe('http://127.0.0.1:8732')
      expect(clientToken()).toBe('new')
      await until(() => sockets.length === 2)
      const second = sockets[1] as FakeSocket
      expect(second.url).toBe('ws://127.0.0.1:8732/api/events')
      second.open()
      expect(second.sent).toEqual([JSON.stringify({ type: 'auth', token: 'new' })])
      second.hello('run-2')
      await until(() => server.count('GET /api/queue') === 2)
      expect(server.requests.at(-1)?.headers.get('Authorization')).toBe('Bearer new')
      expect(useSystemStore().instance).toBe('run-2')
    })

    it('leaves the connection alone when the backend is ready at the same address', async () => {
      const socket = await readyDesktop()
      send({ state: 'ready', info: { ...sidecar } })
      await new Promise((resolve) => setTimeout(resolve, 30))
      expect(sockets).toHaveLength(1)
      expect(socket.closedWith).toBeNull()
    })

    it('connects again with a new token at the same address', async () => {
      const first = await readyDesktop({ initial: 60_000, max: 60_000, factor: 1 })
      send({ state: 'ready', info: { ...sidecar, token: 'new' } })
      expect(clientToken()).toBe('new')
      await until(() => sockets.length === 2)
      expect(first.closedWith).not.toBeNull()
      const second = sockets[1] as FakeSocket
      second.open()
      expect(second.sent).toEqual([JSON.stringify({ type: 'auth', token: 'new' })])
    })

    it('stops following the shell when it is shut down', async () => {
      await readyDesktop()
      shutdown()
      send({ state: 'starting' })
      expect(desktopBackend.value).toEqual({ state: 'ready', info: sidecar })
    })
  })
})
