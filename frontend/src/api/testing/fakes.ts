import type { EventSocket } from '../events'
import type { Problem } from '../types'

export interface Deferred<T> {
  promise: Promise<T>
  resolve(value: T): void
  reject(error: unknown): void
}

export function deferred<T = void>(): Deferred<T> {
  const result: Partial<Deferred<T>> = {}
  result.promise = new Promise<T>((resolve, reject) => {
    result.resolve = resolve
    result.reject = reject
  })
  return result as Deferred<T>
}

/** Lets the promise chains of fake answers and their handlers run to the end. */
export function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 20))
}

export function json(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function problem(status: number, code: string, title: string, detail?: string): Response {
  const body: Problem = { type: 'about:blank', title, status, code, detail: detail ?? null }
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/problem+json' },
  })
}

export interface Recorded {
  method: string
  path: string
  search: string
  headers: Headers
  body: unknown
}

type Handler = (request: Recorded) => unknown

/**
 * A fetch that answers from routes (`'GET /api/queue'`). A handler returns a `Response`, a
 * value sent as JSON, or a promise of either (so a test decides when an answer comes).
 */
export class FakeServer {
  readonly requests: Recorded[] = []
  private readonly routes = new Map<string, Handler>()

  on(route: string, handler: Handler): this
  on(route: string, answer: unknown): this
  on(route: string, handler: unknown): this {
    this.routes.set(
      route,
      typeof handler === 'function' ? (handler as Handler) : () => structuredClone(handler),
    )
    return this
  }

  count(route: string): number {
    return this.requests.filter((request) => `${request.method} ${request.path}` === route).length
  }

  readonly fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = new Request(input, init)
    const url = new URL(request.url)
    const text = await request.text()
    const recorded: Recorded = {
      method: request.method,
      path: url.pathname,
      search: url.search,
      headers: request.headers,
      body: text ? JSON.parse(text) : undefined,
    }
    this.requests.push(recorded)
    const handler = this.routes.get(`${request.method} ${url.pathname}`)
    if (handler === undefined) {
      return problem(404, 'test.no_route', `No route ${request.method} ${url.pathname}`)
    }
    const answer = await handler(recorded)
    return answer instanceof Response ? answer : json(answer)
  }
}

/** A socket a test drives: it opens, receives and closes when the test says so. */
export class FakeSocket implements EventSocket {
  readonly sent: string[] = []
  closedWith: number | null = null
  private readonly listeners = new Map<string, ((event: never) => void)[]>()

  constructor(readonly url: string) {}

  addEventListener(type: string, listener: (event: never) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(code = 1000): void {
    this.closedWith = code
  }

  open(): void {
    this.emit('open', {})
  }

  receive(message: unknown): void {
    this.emit('message', { data: JSON.stringify(message) })
  }

  hello(instance = 'run-1', heartbeat = 15): void {
    this.receive({ type: 'hello', instance, heartbeat, client_id: 'client' })
  }

  /** The server or the network ended the connection. */
  end(code = 1006): void {
    this.emit('close', { code })
  }

  private emit(type: string, event: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) (listener as (e: unknown) => void)(event)
  }
}
