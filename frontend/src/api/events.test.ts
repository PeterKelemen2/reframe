import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  type AnyEvent,
  backoffDelay,
  type ConnectionState,
  EventConnection,
  type EventConnectionOptions,
} from './events'
import { FakeSocket } from './testing/fakes'

const BACKOFF = { initial: 1_000, max: 8_000, factor: 2 }
const MARGIN = 2_000

function setup(options: Partial<EventConnectionOptions> = {}) {
  const sockets: FakeSocket[] = []
  const states: ConnectionState[] = []
  const events: AnyEvent[] = []
  const calls = { hello: 0, gap: 0, unauthorized: 0 }
  let token: string | null = 'secret'
  const connection = new EventConnection({
    url: () => 'ws://server/api/events',
    token: () => token,
    socket: (url) => {
      const socket = new FakeSocket(url)
      sockets.push(socket)
      return socket
    },
    backoff: BACKOFF,
    heartbeatMargin: MARGIN,
    helloTimeout: 5_000,
    stableAfter: 10_000,
    random: () => 0,
    onState: (state) => states.push(state),
    onHello: () => (calls.hello += 1),
    onEvent: (event) => events.push(event),
    onGap: () => (calls.gap += 1),
    onUnauthorized: () => (calls.unauthorized += 1),
    ...options,
  })
  const last = () => sockets.at(-1) as FakeSocket
  const setToken = (value: string | null) => (token = value)
  return { connection, sockets, states, events, calls, last, setToken }
}

function numbered(seq: number): unknown {
  return { type: 'event', seq, event: { type: 'job.log', job_id: 'j', lines: [], dropped: 0 } }
}

describe('EventConnection', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('sends the auth message first: the token, or none for the session cookie', () => {
    const { connection, last, setToken } = setup()
    connection.start()
    last().open()
    expect(last().sent).toEqual([JSON.stringify({ type: 'auth', token: 'secret' })])
    connection.stop()

    setToken(null)
    connection.start()
    last().open()
    expect(last().sent).toEqual([JSON.stringify({ type: 'auth' })])
  })

  it('is open after the hello and passes the events on', () => {
    const { connection, last, states, events, calls } = setup()
    connection.start()
    expect(states).toEqual(['connecting'])
    last().open()
    last().hello()
    last().receive(numbered(1))
    expect(states.at(-1)).toBe('open')
    expect(calls.hello).toBe(1)
    expect(events).toHaveLength(1)
  })

  it('reconnects after a close with a growing, capped backoff', () => {
    const { connection, sockets, last, states } = setup()
    connection.start()
    const delays: number[] = []
    for (let attempt = 0; attempt < 5; attempt += 1) {
      last().end(1006)
      expect(states.at(-1)).toBe('reconnecting')
      const count = sockets.length
      let waited = 0
      while (sockets.length === count) {
        vi.advanceTimersByTime(100)
        waited += 100
      }
      delays.push(waited)
    }
    // `random` 0: half of 1, 2, 4, 8, then 8 (the cap) seconds.
    expect(delays).toEqual([500, 1_000, 2_000, 4_000, 4_000])
  })

  it('starts the backoff again after a connection that stayed open', () => {
    const { connection, sockets, last } = setup()
    connection.start()
    last().end()
    vi.advanceTimersByTime(500)
    last().end()
    vi.advanceTimersByTime(1_000)
    expect(sockets).toHaveLength(3)

    last().open()
    last().hello()
    vi.advanceTimersByTime(10_000)
    last().receive({ type: 'heartbeat' })
    last().end()
    vi.advanceTimersByTime(500)
    expect(sockets).toHaveLength(4)
  })

  it('does not reconnect after a 4401 close', () => {
    const { connection, sockets, last, states, calls } = setup()
    connection.start()
    last().open()
    last().end(4401)
    expect(states.at(-1)).toBe('unauthorized')
    expect(calls.unauthorized).toBe(1)
    vi.advanceTimersByTime(60_000)
    expect(sockets).toHaveLength(1)
  })

  it('reconnects when nothing came for longer than the heartbeat and its margin', () => {
    const { connection, sockets, last } = setup()
    connection.start()
    last().open()
    last().hello('run-1', 15)
    vi.advanceTimersByTime(15_000 + MARGIN - 1)
    last().receive({ type: 'heartbeat' })
    vi.advanceTimersByTime(15_000 + MARGIN - 1)
    expect(sockets).toHaveLength(1)

    vi.advanceTimersByTime(1)
    expect(sockets[0]?.closedWith).not.toBeNull()
    vi.advanceTimersByTime(500)
    expect(sockets).toHaveLength(2)
  })

  it('reconnects when the hello does not come', () => {
    const { connection, sockets, last } = setup()
    connection.start()
    last().open()
    vi.advanceTimersByTime(5_000 + 500)
    expect(sockets).toHaveLength(2)
  })

  it('reports a gap in the event numbers, and none for numbers in order', () => {
    const { connection, last, events, calls } = setup()
    connection.start()
    last().open()
    last().hello()
    last().receive(numbered(1))
    last().receive(numbered(2))
    expect(calls.gap).toBe(0)
    last().receive(numbered(4))
    expect(calls.gap).toBe(1)
    expect(events).toHaveLength(3)
    last().receive(numbered(5))
    expect(calls.gap).toBe(1)
  })

  it('counts the numbers of each connection from 1', () => {
    const { connection, last, calls } = setup()
    connection.start()
    last().open()
    last().hello()
    last().receive(numbered(1))
    last().receive(numbered(2))
    last().end()
    vi.advanceTimersByTime(500)
    last().open()
    last().hello()
    last().receive(numbered(1))
    expect(calls.gap).toBe(0)
  })

  it('stays closed after stop, and ignores what the old socket still sends', () => {
    const { connection, sockets, last, states, events } = setup()
    connection.start()
    const socket = last()
    socket.open()
    socket.hello()
    connection.stop()
    expect(states.at(-1)).toBe('closed')
    expect(socket.closedWith).toBe(1000)
    socket.receive(numbered(1))
    socket.end()
    vi.advanceTimersByTime(60_000)
    expect(sockets).toHaveLength(1)
    expect(events).toEqual([])
  })
})

describe('backoffDelay', () => {
  it('is half fixed and half random, and never above the cap', () => {
    expect(backoffDelay(0, BACKOFF, () => 0)).toBe(500)
    expect(backoffDelay(0, BACKOFF, () => 1)).toBe(1_000)
    expect(backoffDelay(2, BACKOFF, () => 0.5)).toBe(3_000)
    expect(backoffDelay(10, BACKOFF, () => 1)).toBe(8_000)
  })
})
