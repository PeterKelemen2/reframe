import type { AnyEvent, EventSocket } from '../events'

type Listener = (event: never) => void

interface Envelope {
  type: string
  seq?: number
  event?: AnyEvent
}

/**
 * A real WebSocket whose messages a test can hold back or add to: drop events (with or
 * without a gap in the numbers), inject one, or cut the connection without a close handshake.
 */
export class TapSocket implements EventSocket {
  private readonly listeners = new Map<string, Listener[]>()
  private readonly real: WebSocket
  private dead = false
  /** Added to the real numbers: what was injected minus what was dropped without a gap. */
  private shift = 0
  private lastSeq = 0
  /** Events for which this returns true are not passed on. */
  dropWhen: ((event: AnyEvent) => boolean) | null = null
  /** Dropped events leave a gap in the numbers (else the numbers after them are shifted). */
  dropLeavesGap = false
  readonly received: AnyEvent[] = []
  readonly sent: string[] = []
  readonly dropped: AnyEvent[] = []

  constructor(url: string, init?: { headers?: Record<string, string> }) {
    // Node's WebSocket takes headers (the session cookie) as a second argument.
    const Socket = WebSocket as unknown as new (url: string, init?: unknown) => WebSocket
    this.real = init === undefined ? new Socket(url) : new Socket(url, init)
    this.real.addEventListener('open', () => this.emit('open', {}))
    this.real.addEventListener('close', (close) => this.emit('close', { code: close.code }))
    this.real.addEventListener('message', (message) => this.receive(String(message.data)))
  }

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  send(data: string): void {
    this.sent.push(data)
    this.real.send(data)
  }

  close(code?: number): void {
    this.dead = true
    this.real.close(code)
  }

  /** The connection is gone at once, as when the network drops (close code 1006). */
  cut(): void {
    this.dead = true
    this.real.close(4000)
    for (const listener of this.listeners.get('close') ?? []) {
      ;(listener as (close: { code: number }) => void)({ code: 1006 })
    }
  }

  /** Passes `event` on as the next event of the connection. */
  inject(event: AnyEvent): void {
    this.shift += 1
    this.lastSeq += 1
    this.emit('message', { data: JSON.stringify({ type: 'event', seq: this.lastSeq, event }) })
  }

  private receive(data: string): void {
    const message = JSON.parse(data) as Envelope
    if (message.type === 'event' && message.seq !== undefined && message.event !== undefined) {
      this.received.push(message.event)
      if (this.dropWhen?.(message.event)) {
        this.dropped.push(message.event)
        if (!this.dropLeavesGap) this.shift -= 1
        return
      }
      this.lastSeq = message.seq + this.shift
      this.emit('message', { data: JSON.stringify({ ...message, seq: this.lastSeq }) })
      return
    }
    this.emit('message', { data })
  }

  private emit(type: string, event: unknown): void {
    if (this.dead) return
    for (const listener of this.listeners.get(type) ?? []) (listener as (e: unknown) => void)(event)
  }
}
