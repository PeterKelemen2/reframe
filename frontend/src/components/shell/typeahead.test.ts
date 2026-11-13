import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createTypeahead } from './typeahead'

const names = ['Anime', 'Bonus.mkv', 'b-roll.mkv', 'Ball.mkv', 'Movie.mkv']

function key(value: string, init: KeyboardEventInit = {}): KeyboardEvent {
  return new KeyboardEvent('keydown', { key: value, ...init })
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('type-ahead', () => {
  it('moves to the next item that starts with the typed letter, without case', () => {
    const find = createTypeahead()
    expect(find(key('m'), names, 0)).toBe(4)
  })

  it('goes on to the next item with the same letter when it is typed again, and wraps', () => {
    const find = createTypeahead()
    expect(find(key('b'), names, 0)).toBe(1)
    expect(find(key('b'), names, 1)).toBe(2)
    expect(find(key('b'), names, 2)).toBe(3)
    expect(find(key('b'), names, 3)).toBe(1)
  })

  it('matches the keys typed in quick succession, and starts again after a pause', () => {
    const find = createTypeahead()
    expect(find(key('b'), names, 0)).toBe(1)
    expect(find(key('a'), names, 1)).toBe(3)
    vi.advanceTimersByTime(600)
    expect(find(key('a'), names, 3)).toBe(0)
  })

  it('ignores keys with Ctrl, Alt or Meta, and keys that type nothing', () => {
    const find = createTypeahead()
    expect(find(key('a', { ctrlKey: true }), names, 0)).toBeNull()
    expect(find(key('a', { altKey: true }), names, 0)).toBeNull()
    expect(find(key('a', { metaKey: true }), names, 0)).toBeNull()
    expect(find(key('ArrowDown'), names, 0)).toBeNull()
  })

  it('stays put when no item matches', () => {
    expect(createTypeahead()(key('z'), names, 2)).toBeNull()
  })
})
