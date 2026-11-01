import { describe, expect, it } from 'vitest'

import {
  formatTime,
  importPlan,
  namesWith,
  numberedNames,
  shownName,
  START_TOLERANCE,
} from './chapters'
import { chapter } from './testing'

const FULL = [
  chapter(1, 0, 1, 'Opening'),
  chapter(2, 1, 2.5, 'Part One'),
  chapter(3, 2.5, 4, 'Part Two'),
]
// A chapter range 2–3: the output's first chapter is the source's second.
const RANGE = [chapter(1, 0, 1.5, 'Part One', 1), chapter(2, 1.5, 3, 'Part Two', 2)]
const GENERATED = [chapter(1, 0, 300, 'Chapter 1', null), chapter(2, 300, 600, 'Chapter 2', null)]

describe('namesWith', () => {
  it('writes the other chapters as shown, so a rename keeps their names', () => {
    expect(namesWith(null, FULL, new Map([[1, 'Middle']]))).toEqual([
      'Opening',
      'Middle',
      'Part Two',
    ])
    expect(namesWith(['A', 'B', 'C'], FULL, new Map([[2, 'End']]))).toEqual(['A', 'B', 'End'])
  })

  it('renames the source chapter of a range, not the one at the output position', () => {
    expect(namesWith(null, RANGE, new Map([[1, 'Start']]))).toEqual(['', 'Start', 'Part Two'])
  })

  it('keeps the names of source chapters outside the range', () => {
    expect(namesWith(['Intro', 'B', 'C'], RANGE, new Map([[2, 'End']]))).toEqual([
      'Intro',
      'B',
      'End',
    ])
  })

  it('names generated chapters by their place in the output', () => {
    expect(namesWith(null, GENERATED, new Map([[1, 'Second']]))).toEqual(['Chapter 1', 'Second'])
  })
})

describe('shownName', () => {
  it("shows the job's name over an older answer of the server", () => {
    expect(shownName(chapter(2, 1, 2.5, 'Part One'), ['A', 'Renamed', 'C'])).toBe('Renamed')
  })

  it("shows the source chapter's title for an empty name, as the encode writes it", () => {
    expect(shownName(chapter(2, 1, 2.5, 'Stale'), ['A', '', 'C'])).toBe('Part One')
    expect(shownName(chapter(2, 1, 2.5, 'Stale'), null)).toBe('Part One')
  })

  it("shows the server's name for a generated chapter without a name of its own", () => {
    expect(shownName(chapter(1, 0, 300, 'Chapter 1', null), null)).toBe('Chapter 1')
  })
})

it('numbers the chapters by their place in the output, at their source slots', () => {
  expect(numberedNames(null, RANGE, (n) => `Chapter ${n}`)).toEqual(['', 'Chapter 1', 'Chapter 2'])
})

describe('importPlan', () => {
  it('takes the names by position', () => {
    const plan = importPlan(
      [
        { start: 0, name: 'A' },
        { start: 1, name: 'B' },
        { start: 2.5, name: 'C' },
      ],
      RANGE,
    )
    expect([...plan.changes]).toEqual([
      [1, 'A'],
      [2, 'B'],
    ])
    expect(plan.fileCount).toBe(3)
    expect(plan.outputCount).toBe(2)
  })

  it('reports a start that differs by more than the tolerance', () => {
    const plan = importPlan(
      [
        { start: START_TOLERANCE / 2, name: 'A' },
        { start: 1.2, name: 'B' },
        { start: null, name: 'C' },
      ],
      FULL,
    )
    expect(plan.moved).toEqual([{ number: 2, file: 1.2, output: 1 }])
    expect(plan.changes.size).toBe(3)
  })

  it('leaves the chapters a shorter file has no name for', () => {
    const plan = importPlan([{ start: null, name: 'Only' }], FULL)
    expect([...plan.changes]).toEqual([[0, 'Only']])
  })
})

it('formats times with hours and milliseconds', () => {
  expect(formatTime(2.5)).toBe('0:00:02.500')
  expect(formatTime(3725.0004)).toBe('1:02:05.000')
})
