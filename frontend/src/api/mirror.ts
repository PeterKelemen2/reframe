/**
 * A copy of server state that snapshot reads fill and events keep current.
 *
 * Every event the copy uses goes through `event`: it is applied at once and kept for the reads
 * under way. When a read's answer comes, it replaces the state, and the events that came since
 * the read was sent are applied again on top, in order. An event that came before the read was
 * sent is older than the answer; one that came after may be older or newer, so the handlers
 * must reach the same end state either way (a full value per key, or a transition applied only
 * from its `previous` state). So an event that arrives while a read is in flight is not lost,
 * and an answer older than the events after it does not hide them.
 */
export interface Mirror<E> {
  /** Applies the event now and keeps it for the reads and tracked requests under way. */
  event(event: E): void
  /**
   * Reads the snapshot. While a read is in flight, one more read follows it (an event that
   * came before this call may be newer than the read in flight), and its promise is returned.
   */
  read(): Promise<void>
  /**
   * For a handler: the event showed something that only a read gives (a job another front end
   * added, a run's end). A read follows unless one is in flight; that one's replay asks again.
   */
  need(): void
  /** Runs events through the handler again, as `event` does but without keeping them. */
  replay(events: readonly E[]): void
  /**
   * A request whose answer is part of the state (an add's jobs): `apply` gets the answer and
   * the events that came since the request was sent, and replays what concerns it.
   */
  track<T>(request: () => Promise<T>, apply: (answer: T, since: readonly E[]) => void): Promise<T>
  /** A number that grows with each read sent and each call: orders an answer against a read. */
  tick(): number
  readonly reading: boolean
}

export interface MirrorOptions<S, E> {
  fetch: () => Promise<S>
  /** Replaces the state with the snapshot. `sentAt` is the `tick()` of the read's request. */
  apply: (snapshot: S, sentAt: number) => void
  handle: (event: E) => void
  /** A read that nobody awaits failed, or a handler threw. */
  report?: (error: unknown) => void
}

interface Deferred {
  promise: Promise<void>
  resolve: () => void
  reject: (error: unknown) => void
}

function deferred(): Deferred {
  const result: Partial<Deferred> = {}
  result.promise = new Promise<void>((resolve, reject) => {
    result.resolve = resolve
    result.reject = reject
  })
  return result as Deferred
}

export function createMirror<S, E>(options: MirrorOptions<S, E>): Mirror<E> {
  const report = options.report ?? ((error: unknown) => console.error(error))
  const logs = new Set<E[]>()
  let clock = 0
  let current: Promise<void> | null = null
  let following: Deferred | null = null
  let needed = false

  function handle(event: E): boolean {
    needed = false
    try {
      options.handle(event)
    } catch (error) {
      report(error)
    }
    const result = needed
    needed = false
    return result
  }

  function live(event: E): void {
    // During a read the event is in its log (or older than its answer): its replay decides.
    if (handle(event) && current === null) void background()
  }

  function background(): Promise<void> {
    const promise = read()
    promise.catch(report)
    return promise
  }

  async function run(): Promise<void> {
    const log: E[] = []
    logs.add(log)
    const sentAt = ++clock
    let again = false
    try {
      const snapshot = await options.fetch()
      logs.delete(log)
      options.apply(snapshot, sentAt)
      for (const event of log) if (handle(event)) again = true
    } finally {
      logs.delete(log)
      current = null
      const next = following
      following = null
      if (next !== null || again) {
        const chained = run()
        current = chained
        if (next !== null) chained.then(next.resolve, next.reject)
        else chained.catch(report)
      }
    }
  }

  function read(): Promise<void> {
    if (current === null) {
      current = run()
      return current
    }
    following ??= deferred()
    return following.promise
  }

  return {
    event(event) {
      for (const log of logs) log.push(event)
      live(event)
    },
    read,
    need() {
      needed = true
    },
    replay(events) {
      for (const event of events) live(event)
    },
    async track(request, apply) {
      const log: E[] = []
      logs.add(log)
      try {
        const answer = await request()
        logs.delete(log)
        apply(answer, log)
        return answer
      } finally {
        logs.delete(log)
      }
    },
    tick() {
      return ++clock
    },
    get reading() {
      return current !== null
    },
  }
}
