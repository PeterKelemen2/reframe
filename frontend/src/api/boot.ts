/**
 * The app's connection to the server: credentials, the auth status, the event connection and
 * the snapshots. `system.auth` drives it: credentials that become valid (a login) start the
 * session, credentials that stop being valid (a 401, a 4401, a logout) end it.
 */
import { shallowRef, watch } from 'vue'

import { platform } from '@/platform'
import type {
  DesktopBackend,
  DesktopBackendError,
  DesktopBackendState,
  DesktopShell,
} from '@/platform/types'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'
import { useQueueStore } from '@/stores/queue'
import { useTasksStore } from '@/stores/tasks'

import {
  ApiError,
  apiQuiet,
  clientBaseUrl,
  clientToken,
  configureClient,
  onUnauthorized,
  unwrap,
} from './client'
import { storeToken, storedToken, takeFragmentToken } from './credentials'
import { dispatch, guard, resyncAll } from './dispatch'
import {
  type Backoff,
  backoffDelay,
  EventConnection,
  type EventConnectionOptions,
  type SocketFactory,
} from './events'
import type { Schemas } from './types'

type Hello = Schemas['Hello']

// The router reads the address when it is created, after this module: the token must be gone
// from the address (and the history entry) before that.
const addressToken = typeof window === 'undefined' ? null : takeFragmentToken()

/** Retries of a server that cannot be reached at start (milliseconds). */
export const OFFLINE_BACKOFF: Backoff = { initial: 1_000, max: 30_000, factor: 2 }
/** How long the first snapshots wait for the event connection's hello. */
export const HELLO_WAIT = 3_000

export interface BootOptions {
  /** Default: `platform.backend()`. Not used with a desktop shell. */
  backend?: () => Promise<{ baseUrl: string; token?: string }>
  /** Default: `platform.desktop`. */
  desktop?: DesktopShell | null
  /** The web build's token. Default: the address fragment's, else the tab's stored one. */
  token?: string | null
  socket?: SocketFactory
  fetch?: typeof globalThis.fetch
  offlineBackoff?: Backoff
  helloWait?: number
  random?: () => number
  connection?: Pick<
    EventConnectionOptions,
    'backoff' | 'heartbeatMargin' | 'helloTimeout' | 'stableAfter'
  >
}

function eventsUrl(): string {
  const url = new URL('/api/events', clientBaseUrl() || globalThis.location.origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function offline(error: unknown): boolean {
  return error instanceof ApiError && error.status === 0
}

/** Tries until `attempt` gives a value; `pause(n)` waits before try `n + 1`. */
async function retrying<T>(
  attempt: () => Promise<T | undefined>,
  pause: (n: number) => Promise<void>,
  n = 0,
): Promise<T> {
  const result = await attempt()
  if (result !== undefined) return result
  await pause(n)
  return retrying(attempt, pause, n + 1)
}

interface Session {
  connection: EventConnection
  stop(): void
}

/** What the desktop shell last said of its backend; `null` in a browser. */
export const desktopBackend = shallowRef<DesktopBackendState | null>(null)

/**
 * The desktop shell's backend once it is ready (after a failure, a Retry can still make it
 * ready). `changed` gets every later ready backend.
 */
function followDesktop(
  shell: DesktopShell,
  changed: (info: DesktopBackend) => void,
): { ready: Promise<DesktopBackend>; stop: () => void } {
  let first: ((info: DesktopBackend) => void) | null = null
  const ready = new Promise<DesktopBackend>((resolve) => (first = resolve))
  function apply(state: DesktopBackendState): void {
    desktopBackend.value = state
    if (state.state !== 'ready') return
    if (first === null) changed(state.info)
    else {
      first(state.info)
      first = null
    }
  }
  // Subscribed before the question, so no change after the answer is missed.
  const stop = shell.onBackendState(apply)
  shell.backendInfo().then(
    (info) => apply({ state: 'ready', info }),
    (error: DesktopBackendError) => apply({ state: 'failed', error }),
  )
  return { ready, stop }
}

let current: Session | null = null

/**
 * Starts the app's connection to the server, once, after the plugins are installed. Resolves
 * when the app is `ready` or shows the login (a server that cannot be reached is retried, with
 * `phase` `offline`, until it answers).
 */
export async function boot(options: BootOptions = {}): Promise<void> {
  current?.stop()
  const system = useSystemStore()
  const tasks = useTasksStore()
  const queue = useQueueStore()
  const random = options.random ?? Math.random
  const offlineBackoff = options.offlineBackoff ?? OFFLINE_BACKOFF

  const shell = options.desktop !== undefined ? options.desktop : platform.desktop
  let restartConnection: (() => void) | null = null
  const desktop =
    shell === null
      ? null
      : followDesktop(shell, (info) => {
          if (info.baseUrl === clientBaseUrl() && info.token === clientToken()) return
          configureClient({ baseUrl: info.baseUrl, token: info.token })
          restartConnection?.()
        })
  const backend = await (desktop?.ready ?? (options.backend ?? (() => platform.backend()))())
  const token =
    backend.token ?? (options.token !== undefined ? options.token : (addressToken ?? storedToken()))
  if (backend.token === undefined) storeToken(token)
  configureClient({ baseUrl: backend.baseUrl, token, fetch: options.fetch ?? null })

  let running: Promise<void> | null = null
  let loadStarted = false
  let firstHello: (() => void) | null = null

  function onHello(hello: Hello): void {
    const previous = system.instance
    system.instance = hello.instance
    if (previous !== null && previous !== hello.instance) {
      // A new server run forgot the probed sources and may bring other definitions.
      guard('sources.onServerRestart', () => useSourcesStore().onServerRestart())
      guard('system.loadDefinitions', () => system.loadDefinitions())
    }
    if (loadStarted) resyncAll()
    else firstHello?.()
  }

  const connection = new EventConnection({
    ...options.connection,
    url: eventsUrl,
    token: clientToken,
    socket: options.socket,
    random,
    onState: (state) => (system.connection = state),
    onHello,
    onEvent: dispatch,
    onGap: resyncAll,
    onUnauthorized: () => signOut(),
  })

  function signOut(): void {
    if (system.auth?.authenticated) system.auth = { ...system.auth, authenticated: false }
  }

  let closed = false

  async function pause(attempt: number): Promise<void> {
    system.phase = 'offline'
    await sleep(backoffDelay(attempt, offlineBackoff, random))
    if (closed) throw new Error('boot was shut down')
  }

  async function load(): Promise<void> {
    await retrying(async () => {
      const results = await Promise.allSettled([
        system.loadDefinitions(),
        system.resync(),
        tasks.resync(),
        queue.resync(),
      ])
      const unreachable = results.some(
        (result) => result.status === 'rejected' && offline(result.reason),
      )
      return unreachable ? undefined : true
    }, pause)
  }

  function start(): Promise<void> {
    running ??= (async () => {
      system.phase = 'booting'
      loadStarted = false
      const hello = new Promise<void>((resolve) => {
        firstHello = resolve
        setTimeout(resolve, options.helloWait ?? HELLO_WAIT)
      })
      connection.start()
      await hello
      firstHello = null
      // Every snapshot read comes after the hello: events published since are on their way.
      loadStarted = true
      await load()
      if (system.auth?.authenticated) system.phase = 'ready'
    })()
    return running
  }

  // A restarted sidecar listens elsewhere: connect there now, not after the retry's backoff.
  restartConnection = () => {
    if (running === null) return
    connection.stop()
    connection.start()
  }

  function end(): void {
    running = null
    if (system.connection !== 'unauthorized') connection.stop()
    system.phase = 'login'
  }

  const stopWatch = watch(
    () => system.auth?.authenticated ?? false,
    (authenticated) => (authenticated ? void start() : end()),
    { flush: 'sync' },
  )
  const stopListening = onUnauthorized(signOut)
  current = {
    connection,
    stop() {
      closed = true
      desktop?.stop()
      stopWatch()
      stopListening()
      connection.stop()
    },
  }

  const status = await retrying(async () => {
    try {
      return unwrap(await apiQuiet.GET('/api/auth/status'))
    } catch {
      return undefined
    }
  }, pause)
  if (!status.authenticated && status.mode === 'token' && token !== null) {
    // A token the server does not take (another run's, or a mistyped one).
    configureClient({ token: null })
    storeToken(null)
  }
  system.auth = status
  if (status.authenticated) await start()
  else system.phase = 'login'
}

/** Closes the event connection and stops following the credentials (tests, a new `boot`). */
export function shutdown(): void {
  current?.stop()
  current = null
}
