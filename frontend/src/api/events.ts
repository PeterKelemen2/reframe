/**
 * The client of `WS /api/events`: the auth message first, then the hello and the numbered
 * events. It reconnects after any close but 4401 and after a silence longer than the hello's
 * heartbeat, with an exponential backoff and jitter.
 */
import type { QueueProcessingEvent, ReframeEvent, Schemas } from './types'

type Hello = Schemas['Hello']

export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'unauthorized' | 'closed'

/** A core event, or one the generated schema does not list yet. */
export type AnyEvent = ReframeEvent | QueueProcessingEvent

/** The part of a browser `WebSocket` the connection uses. */
export interface EventSocket {
  send(data: string): void
  close(code?: number): void
  addEventListener(type: 'open', listener: () => void): void
  addEventListener(type: 'message', listener: (message: { data: unknown }) => void): void
  addEventListener(type: 'close', listener: (close: { code: number }) => void): void
}

/** Makes the socket; tests pass one that can drop the connection or a message. */
export type SocketFactory = (url: string) => EventSocket

/** Milliseconds. */
export interface Backoff {
  initial: number
  max: number
  factor: number
}

export const RECONNECT_BACKOFF: Backoff = { initial: 500, max: 30_000, factor: 2 }
/** Silence beyond the hello's heartbeat before the connection counts as dead. */
export const HEARTBEAT_MARGIN = 5_000
export const HELLO_TIMEOUT = 10_000
/** A connection open this long starts the backoff from the beginning when it ends. */
export const STABLE_AFTER = 10_000
/** The server closes with this when the auth message is refused. */
export const UNAUTHORIZED = 4401
const NO_HEARTBEAT = 4000

/** The delay before reconnect `attempt` (0 first): half fixed, half random, so clients spread. */
export function backoffDelay(attempt: number, backoff: Backoff, random: () => number): number {
  const ceiling = Math.min(backoff.max, backoff.initial * backoff.factor ** attempt)
  return ceiling / 2 + (random() * ceiling) / 2
}

export interface EventConnectionOptions {
  /** The `ws:` or `wss:` address of `/api/events`. */
  url: () => string
  /** The auth message's token; `null`: the session cookie stands in for it. */
  token: () => string | null
  socket?: SocketFactory
  backoff?: Backoff
  heartbeatMargin?: number
  helloTimeout?: number
  stableAfter?: number
  random?: () => number
  onState(state: ConnectionState): void
  onHello(hello: Hello): void
  onEvent(event: AnyEvent): void
  /** An event number was skipped: the copies may have missed something. */
  onGap(): void
  /** The server refused the credentials (4401); the connection stays closed. */
  onUnauthorized(): void
}

type Message = Hello | { type: 'event'; seq: number; event: AnyEvent } | { type: 'heartbeat' }

function parse(data: unknown): Message | null {
  try {
    const message: unknown = JSON.parse(String(data))
    if (typeof message === 'object' && message !== null && 'type' in message) {
      return message as Message
    }
  } catch {
    // Not JSON: ignored like a message of an unknown type.
  }
  return null
}

export class EventConnection {
  private socket: EventSocket | null = null
  private running = false
  private attempt = 0
  private expected = 1
  private openedAt: number | null = null
  /** The hello's interval in seconds; `null` until the hello. */
  private heartbeat: number | null = null
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private watchdog: ReturnType<typeof setTimeout> | null = null

  constructor(private readonly options: EventConnectionOptions) {}

  start(): void {
    if (this.running) return
    this.running = true
    this.attempt = 0
    this.connect('connecting')
  }

  /** Closes the connection for good (until `start`). */
  stop(state: 'closed' | 'unauthorized' = 'closed'): void {
    this.running = false
    this.clearTimers()
    this.drop()
    this.options.onState(state)
  }

  private connect(state: 'connecting' | 'reconnecting'): void {
    this.retryTimer = null
    this.options.onState(state)
    const create = this.options.socket ?? ((url: string) => new WebSocket(url))
    let socket: EventSocket
    try {
      socket = create(this.options.url())
    } catch {
      this.reconnect()
      return
    }
    this.socket = socket
    this.expected = 1
    socket.addEventListener('open', () => {
      if (socket !== this.socket) return
      const token = this.options.token()
      socket.send(JSON.stringify(token === null ? { type: 'auth' } : { type: 'auth', token }))
      this.arm(this.options.helloTimeout ?? HELLO_TIMEOUT)
    })
    socket.addEventListener('message', (message) => {
      if (socket === this.socket) this.receive(message.data)
    })
    socket.addEventListener('close', (close) => {
      if (socket !== this.socket) return
      this.socket = null
      this.clearTimers()
      if (close.code === UNAUTHORIZED) {
        this.stop('unauthorized')
        this.options.onUnauthorized()
        return
      }
      this.reconnect()
    })
  }

  private receive(data: unknown): void {
    const message = parse(data)
    if (message === null) return
    if (message.type === 'hello') {
      this.openedAt = Date.now()
      this.heartbeat = message.heartbeat
      this.arm(this.heartbeatDeadline(message.heartbeat))
      this.options.onState('open')
      this.options.onHello(message)
      return
    }
    if (this.heartbeat !== null) this.arm(this.heartbeatDeadline(this.heartbeat))
    if (message.type !== 'event') return
    const gap = message.seq !== this.expected
    this.expected = message.seq + 1
    this.options.onEvent(message.event)
    if (gap) this.options.onGap()
  }

  private heartbeatDeadline(seconds: number): number {
    return seconds * 1000 + (this.options.heartbeatMargin ?? HEARTBEAT_MARGIN)
  }

  /** Nothing arrived in time: the connection is dead even if the browser has not noticed. */
  private arm(timeout: number): void {
    if (this.watchdog !== null) clearTimeout(this.watchdog)
    this.watchdog = setTimeout(() => {
      this.watchdog = null
      this.drop(NO_HEARTBEAT)
      this.reconnect()
    }, timeout)
  }

  private drop(code = 1000): void {
    const socket = this.socket
    this.socket = null
    this.heartbeat = null
    if (socket === null) return
    try {
      socket.close(code)
    } catch {
      // Already closing.
    }
  }

  private reconnect(): void {
    if (!this.running) return
    if (
      this.openedAt !== null &&
      Date.now() - this.openedAt >= (this.options.stableAfter ?? STABLE_AFTER)
    ) {
      this.attempt = 0
    }
    this.openedAt = null
    const delay = backoffDelay(
      this.attempt,
      this.options.backoff ?? RECONNECT_BACKOFF,
      this.options.random ?? Math.random,
    )
    this.attempt += 1
    this.options.onState('reconnecting')
    this.retryTimer = setTimeout(() => this.connect('reconnecting'), delay)
  }

  private clearTimers(): void {
    if (this.retryTimer !== null) clearTimeout(this.retryTimer)
    if (this.watchdog !== null) clearTimeout(this.watchdog)
    this.retryTimer = null
    this.watchdog = null
  }
}
