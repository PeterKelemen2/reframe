/** One request at a time for state that keeps changing; only the newest one's answer counts. */
export interface LatestRequest {
  /**
   * Sends after `delay` ms. A request that is waiting or under way is dropped: it is aborted
   * and its answer, if one still comes, is never handed on.
   */
  schedule(delay: number): void
  /** Drops the waiting or running request. */
  cancel(): void
}

export interface LatestOptions<T> {
  /** Reads the state when the request goes out; `signal` aborts it. */
  send(signal: AbortSignal): Promise<T>
  done(value: T): void
  failed(error: unknown): void
}

export function latestRequest<T>(options: LatestOptions<T>): LatestRequest {
  let generation = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | null = null

  function cancel(): void {
    generation += 1
    clearTimeout(timer)
    timer = undefined
    controller?.abort()
    controller = null
  }

  async function fire(mine: number): Promise<void> {
    timer = undefined
    const own = new AbortController()
    controller = own
    let value: T
    try {
      value = await options.send(own.signal)
    } catch (error) {
      if (mine !== generation) return
      controller = null
      options.failed(error)
      return
    }
    if (mine !== generation) return
    controller = null
    options.done(value)
  }

  function schedule(delay: number): void {
    cancel()
    const mine = generation
    timer = setTimeout(() => void fire(mine), delay)
  }

  return { schedule, cancel }
}
