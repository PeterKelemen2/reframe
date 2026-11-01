import createClient, { type Client, type Middleware } from 'openapi-fetch'

import { useToastStore } from '@/stores/toasts'

import { text } from './text'
import type { paths, Problem } from './types'

export type ApiClient = Client<paths>

interface Connection {
  baseUrl: string
  token: string | null
  fetch: typeof globalThis.fetch | null
}

const connection: Connection = { baseUrl: '', token: null, fetch: null }
const unauthorizedListeners = new Set<() => void>()

/**
 * Where the server is and how to authenticate. `token` is sent as `Authorization: Bearer`;
 * without one the browser's session cookie (password mode) is all there is. `fetch` replaces
 * the global one (tests).
 */
export function configureClient(options: Partial<Connection>): void {
  Object.assign(connection, options)
}

export function clientBaseUrl(): string {
  return connection.baseUrl
}

export function clientToken(): string | null {
  return connection.token
}

/** Calls `listener` after every 401 answer, of either client. Returns the unsubscribe. */
export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener)
  return () => unauthorizedListeners.delete(listener)
}

// openapi-fetch builds a `Request` before any middleware runs, and a relative URL only works
// where there is a document to resolve it against.
class ApiRequest extends Request {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(typeof input === 'string' ? new URL(input, base()) : input, init)
  }
}

function base(): string {
  return connection.baseUrl || globalThis.location.origin
}

async function send(request: Request): Promise<Response> {
  if (connection.token !== null && !request.headers.has('Authorization')) {
    request.headers.set('Authorization', `Bearer ${connection.token}`)
  }
  const response = await (connection.fetch ?? globalThis.fetch)(request)
  if (response.status === 401) for (const listener of unauthorizedListeners) listener()
  return response
}

/** An answer that was not 2xx; `status` 0: the server could not be reached. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Problem,
  ) {
    super(problem.detail ?? problem.title)
    this.name = 'ApiError'
  }
}

function isProblem(value: unknown): value is Problem {
  if (typeof value !== 'object' || value === null) return false
  const problem = value as Record<string, unknown>
  return typeof problem.title === 'string' && typeof problem.code === 'string'
}

/** The problem of an answer that was not 2xx; a body that is not one gets a generic one. */
export function problemOf(body: unknown, response: Response): Problem {
  if (isProblem(body)) return body
  return {
    type: 'about:blank',
    title: text('api.answered', { status: response.status }),
    status: response.status,
    code: `http.${response.status}`,
  }
}

function unreachable(): Problem {
  return { type: 'about:blank', title: text('api.unreachable'), status: 0, code: 'network' }
}

/** The `data` of an openapi-fetch result, or an `ApiError` thrown for its `error`. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok) {
    throw new ApiError(result.response.status, problemOf(result.error, result.response))
  }
  return result.data as T
}

/** A failed request becomes an `ApiError` with status 0, so every caller handles one type. */
const networkErrors: Middleware = {
  onError({ error }) {
    if (error instanceof DOMException && error.name === 'AbortError') return
    return new ApiError(0, unreachable())
  },
}

const TOAST_LIFE = 10_000
let unreachableToast: number | null = null

const toastProblems: Middleware = {
  async onResponse({ response }) {
    // A 401 shows the login screen; a toast would only repeat it.
    if (response.ok || response.status === 401) return
    let body: unknown
    try {
      body = JSON.parse(await response.clone().text())
    } catch {
      body = undefined
    }
    const problem = problemOf(body, response)
    useToastStore().push({
      severity: 'error',
      summary: problem.title,
      detail: problem.detail ?? undefined,
      life: TOAST_LIFE,
    })
  },
  onError({ error }) {
    if (!(error instanceof ApiError) || error.status !== 0) return
    const toasts = useToastStore()
    // One at a time: a lost server fails every request.
    if (unreachableToast !== null && toasts.items.some((toast) => toast.id === unreachableToast)) {
      return
    }
    unreachableToast = toasts.push({
      severity: 'error',
      summary: error.problem.title,
      detail: text('api.unreachableDetail'),
      life: TOAST_LIFE,
    })
  },
}

function client(): ApiClient {
  return createClient<paths>({ Request: ApiRequest, fetch: send })
}

/** The typed client. A problem+json answer and a failed request are also shown as a toast. */
export const api: ApiClient = client()
// openapi-fetch runs `onError` from the last middleware to the first: the toast sees the
// `ApiError` that `networkErrors` made.
api.use(toastProblems, networkErrors)

/** The same client without the toast: the caller shows the problem itself (a form, a field). */
export const apiQuiet: ApiClient = client()
apiQuiet.use(networkErrors)
