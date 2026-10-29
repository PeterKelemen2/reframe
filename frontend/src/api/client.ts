import createClient, { type Client } from 'openapi-fetch'

import { notBuilt } from '@/notBuilt'

import type { paths, Problem } from './types'

export type ApiClient = Client<paths>

/** The typed client. A problem+json answer is also shown as a toast. */
export const api: ApiClient = createClient<paths>()

/** The same client without the toast: the caller shows the problem itself (a form, a field). */
export const apiQuiet: ApiClient = createClient<paths>()

/** An answer that was not 2xx. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Problem,
  ) {
    super(problem.detail ?? problem.title)
    this.name = 'ApiError'
  }
}

/** The `data` of an openapi-fetch result, or an `ApiError` thrown for its `error`. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  return notBuilt('unwrap', result)
}
