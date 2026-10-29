import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'
import { useToastStore } from '@/stores/toasts'

import { boot, shutdown } from './boot'
import { type DevServer, startServer } from './testing/devServer.mjs'
import { TapSocket } from './testing/tapSocket'

const PORT = 8722
const PASSWORD = 'correct horse battery'

/** Events and reads take milliseconds; this leaves room for a loaded machine. */
const SOON = { timeout: 10_000, interval: 50 }

let server: DevServer
let sockets: TapSocket[]
/** The session cookie, as a browser keeps it: set by the answers, sent with every request. */
let cookies: Map<string, string>
let requests: Request[]

function cookieHeader(): string {
  return [...cookies].map(([name, value]) => `${name}=${value}`).join('; ')
}

async function browserFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const request = new Request(input, init)
  if (cookies.size > 0) request.headers.set('cookie', cookieHeader())
  requests.push(request.clone())
  const response = await fetch(request)
  for (const line of response.headers.getSetCookie()) {
    const [pair = ''] = line.split(';')
    const [name = '', value = ''] = pair.split('=')
    if (value === '' || /max-age=0/i.test(line)) cookies.delete(name)
    else cookies.set(name, value)
  }
  return response
}

async function bootClient(): Promise<void> {
  await boot({
    backend: async () => ({ baseUrl: server.url }),
    token: null,
    fetch: browserFetch,
    socket: (url) => {
      const socket = new TapSocket(url, { headers: { cookie: cookieHeader() } })
      sockets.push(socket)
      return socket
    },
  })
}

beforeAll(async () => {
  server = await startServer({ port: PORT, args: ['--auth', 'password', '--password', PASSWORD] })
})

afterAll(async () => {
  await server.stop()
})

beforeEach(() => {
  setActivePinia(createPinia())
  sockets = []
  cookies = new Map()
  requests = []
})

afterEach(() => {
  shutdown()
})

describe('password login against a real server', () => {
  it('shows the login until a password is accepted, then works with the session cookie only', async () => {
    await bootClient()
    const system = useSystemStore()
    expect(system.auth).toEqual({ mode: 'password', authenticated: false })
    expect(system.phase).toBe('login')
    expect(sockets).toHaveLength(0)

    expect(await system.login('wrong password')).toBe(false)
    expect(system.phase).toBe('login')
    expect(useToastStore().items).toEqual([])

    expect(await system.login(PASSWORD)).toBe(true)
    expect(cookies.has('reframe_session')).toBe(true)
    await vi.waitFor(() => expect(system.phase).toBe('ready'), SOON)
    expect(system.connection).toBe('open')
    expect(sockets[0]?.sent).toEqual([JSON.stringify({ type: 'auth' })])
    expect(useQueueStore().loaded).toBe(true)
    expect(system.info?.auth).toBe('password')
    expect(requests.every((request) => !request.headers.has('authorization'))).toBe(true)
  })

  it('goes back to the login after a logout, and the cookie no longer opens the API', async () => {
    await bootClient()
    const system = useSystemStore()
    expect(await system.login(PASSWORD)).toBe(true)
    await vi.waitFor(() => expect(system.phase).toBe('ready'), SOON)
    const session = cookieHeader()

    await system.logout()
    expect(system.phase).toBe('login')
    expect(system.connection).toBe('closed')
    const answer = await fetch(`${server.url}/api/queue`, { headers: { cookie: session } })
    expect(answer.status).toBe(401)
  })
})
