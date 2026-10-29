import { describe, expect, it } from 'vitest'

import { EMPTY_HISTORY, endRun, type History, record, redoStep, undoStep } from './history'
import { applyOps } from './patch'

const v = (value: number) => ({ quality: value, encoder: 'libx265' })

describe('the undo history', () => {
  it('records each change as a step whose patches go both ways', () => {
    const history = record(EMPTY_HISTORY, v(22), v(20))
    expect(history.done).toHaveLength(1)
    const [step] = history.done
    expect(applyOps(v(22), step?.redo ?? [])).toEqual(v(20))
    expect(applyOps(v(20), step?.undo ?? [])).toEqual(v(22))
  })

  it('makes patches in a row with one key one step from the first state to the last', () => {
    let history = EMPTY_HISTORY
    for (let value = 22; value > 15; value -= 1) {
      history = record(history, v(value), v(value - 1), 'quality')
    }
    expect(history.done).toHaveLength(1)
    expect(applyOps(v(15), history.done[0]?.undo ?? [])).toEqual(v(22))
  })

  it('starts a new step for another key, for a patch without a key and after endRun', () => {
    let history = record(EMPTY_HISTORY, v(22), v(21), 'quality')
    history = record(history, v(21), { ...v(21), encoder: 'libx264' }, 'encoder')
    expect(history.done).toHaveLength(2)
    history = record(history, v(21), v(20))
    history = record(history, v(20), v(19))
    expect(history.done).toHaveLength(4)
    history = record(history, v(19), v(18), 'quality')
    history = endRun(history)
    history = record(history, v(18), v(17), 'quality')
    expect(history.done).toHaveLength(6)
  })

  it('leaves no step when a run comes back to where it started', () => {
    let history = record(EMPTY_HISTORY, v(22), v(21), 'quality')
    history = record(history, v(21), v(22), 'quality')
    expect(history.done).toHaveLength(0)
    history = record(history, v(22), v(25), 'quality')
    expect(history.done).toHaveLength(1)
    expect(applyOps(v(25), history.done[0]?.undo ?? [])).toEqual(v(22))
  })

  it('drops the steps to redo on a change, and keeps them for a change that changes nothing', () => {
    const undone = undoStep(record(EMPTY_HISTORY, v(22), v(20)))?.history as History
    expect(undone.undone).toHaveLength(1)
    expect(record(undone, v(22), v(22)).undone).toHaveLength(1)
    expect(record(undone, v(22), v(22), 'quality').undone).toHaveLength(1)
    expect(record(undone, v(22), v(23)).undone).toHaveLength(0)
  })

  it('moves steps between done and undone, and ends a run', () => {
    const history = record(record(EMPTY_HISTORY, v(22), v(21)), v(21), v(20), 'quality')
    const undone = undoStep(history)
    expect(undone?.step).toBe(history.done[1])
    expect(undone?.history.done).toHaveLength(1)
    expect(undone?.history.run).toBeNull()
    const redone = redoStep(undone?.history as History)
    expect(redone?.step).toBe(history.done[1])
    expect(redone?.history.done).toHaveLength(2)
    expect(redone?.history.undone).toHaveLength(0)
    expect(undoStep(EMPTY_HISTORY)).toBeNull()
    expect(redoStep(history)).toBeNull()
  })

  it('keeps the newest steps up to its limit', () => {
    let history = EMPTY_HISTORY
    for (let value = 0; value < 5; value += 1)
      history = record(history, v(value), v(value + 1), null, 3)
    expect(history.done).toHaveLength(3)
    expect(applyOps(v(5), history.done[2]?.undo ?? [])).toEqual(v(4))
    expect(applyOps(v(3), history.done[0]?.undo ?? [])).toEqual(v(2))
  })
})
