import { describe, expect, it, vi } from 'vitest'

import { createMirror } from './mirror'
import { type Deferred, deferred, settle } from './testing/fakes'

interface Change {
  key: string
  value: number
  /** The handler asks for a read when it sees this event (while the state lacks `key`). */
  needs?: boolean
}

function setup() {
  const state = new Map<string, number>()
  const answers: Deferred<Record<string, number>>[] = []
  const report = vi.fn<(error: unknown) => void>()
  const mirror = createMirror<Record<string, number>, Change>({
    fetch: () => {
      const answer = deferred<Record<string, number>>()
      answers.push(answer)
      return answer.promise
    },
    apply(snapshot) {
      state.clear()
      for (const [key, value] of Object.entries(snapshot)) state.set(key, value)
    },
    handle(change) {
      if (change.key === 'boom') throw new Error('broken handler')
      if (change.needs && !state.has(change.key)) {
        mirror.need()
        return
      }
      state.set(change.key, change.value)
    },
    report,
  })
  return { state, answers, mirror, report }
}

describe('createMirror', () => {
  it('applies an event that came during a read again on top of the answer', async () => {
    const { state, answers, mirror } = setup()
    const read = mirror.read()
    mirror.event({ key: 'a', value: 2 })
    expect(state.get('a')).toBe(2)

    answers[0]?.resolve({ a: 1, b: 7 })
    await read
    expect(state.get('a')).toBe(2)
    expect(state.get('b')).toBe(7)
  })

  it('does not apply an event that came before the read again', async () => {
    const { state, answers, mirror } = setup()
    mirror.event({ key: 'a', value: 1 })
    const read = mirror.read()
    answers[0]?.resolve({ a: 2 })
    await read
    expect(state.get('a')).toBe(2)
  })

  it('reads once more after the read in flight when asked during it', async () => {
    const { state, answers, mirror } = setup()
    const first = mirror.read()
    const second = mirror.read()
    const third = mirror.read()
    expect(answers).toHaveLength(1)

    answers[0]?.resolve({ a: 1 })
    await first
    await settle()
    expect(answers).toHaveLength(2)
    let secondDone = false
    void second.then(() => (secondDone = true))
    await settle()
    expect(secondDone).toBe(false)

    answers[1]?.resolve({ a: 2 })
    await Promise.all([second, third])
    expect(state.get('a')).toBe(2)
    expect(answers).toHaveLength(2)
  })

  it('reads when an event needs it, and not again when the read in flight answers it', async () => {
    const { state, answers, mirror } = setup()
    mirror.event({ key: 'x', value: 1, needs: true })
    expect(answers).toHaveLength(1)

    mirror.event({ key: 'y', value: 1, needs: true })
    answers[0]?.resolve({ x: 1, y: 2 })
    await settle()
    expect(answers).toHaveLength(1)
    expect(state.get('y')).toBe(1)
  })

  it('reads again when the replay on an answer still needs it, and not when it does not', async () => {
    const { state, answers, mirror } = setup()
    const read = mirror.read()
    mirror.event({ key: 'x', value: 1, needs: true })
    mirror.event({ key: 'y', value: 1, needs: true })

    // The answer has `x` (it was newer), not `y`: one more read, for `y`.
    answers[0]?.resolve({ x: 5 })
    await read
    await settle()
    expect(state.get('x')).toBe(1)
    expect(answers).toHaveLength(2)

    answers[1]?.resolve({ x: 5, y: 3 })
    await settle()
    expect(answers).toHaveLength(2)
    expect(state.get('y')).toBe(3)
  })

  it('goes on with the replay after a handler throws', async () => {
    const { state, answers, mirror, report } = setup()
    const read = mirror.read()
    mirror.event({ key: 'boom', value: 1 })
    mirror.event({ key: 'a', value: 2 })
    answers[0]?.resolve({})
    await read
    expect(state.get('a')).toBe(2)
    expect(report).toHaveBeenCalledTimes(2)
  })

  it('rejects a failed read, keeps the state and still runs the read asked for during it', async () => {
    const { state, answers, mirror } = setup()
    mirror.event({ key: 'a', value: 1 })
    const failing = mirror.read()
    const next = mirror.read()
    answers[0]?.reject(new Error('offline'))
    await expect(failing).rejects.toThrow('offline')
    expect(state.get('a')).toBe(1)

    await settle()
    answers[1]?.resolve({ a: 4 })
    await next
    expect(state.get('a')).toBe(4)
  })

  it('hands a tracked answer the events that came since its request', async () => {
    const { mirror } = setup()
    mirror.event({ key: 'before', value: 1 })
    const answer = deferred<string>()
    const apply = vi.fn<(answer: string, since: readonly Change[]) => void>()
    const tracked = mirror.track(() => answer.promise, apply)
    mirror.event({ key: 'during', value: 2 })
    answer.resolve('added')
    expect(await tracked).toBe('added')
    expect(apply).toHaveBeenCalledWith('added', [{ key: 'during', value: 2 }])
  })
})
