import { describe, expect, it } from 'vitest'

import type { MatrixColumn, Resolution } from '@/api/types'

import { cellRank, pickedByHand, rowLabels, sortRows, trackText } from './matrix'
import { animeResolution, animeSources } from './testing'

function anime() {
  const resolution = animeResolution()
  const rows = resolution.rows ?? []
  const labels = rowLabels(rows, resolution.group?.members ?? [])
  return { resolution, items: rows.map((row, index) => ({ row, label: labels[index] })) }
}

function column(label: string): MatrixColumn {
  const found = animeResolution().columns?.find((candidate) => candidate.label.startsWith(label))
  if (found === undefined) throw new Error(label)
  return found
}

function at(columns: MatrixColumn[], label: string): number {
  return columns.findIndex((candidate) => candidate.label.startsWith(label))
}

describe('rowLabels', () => {
  it('labels members by episode, a file that is no member by its file name', () => {
    const { resolution } = anime()
    const rows = resolution.rows ?? []
    const members = (resolution.group?.members ?? []).filter((m) => !m.path.includes('E12'))
    const labels = rowLabels(rows, members)
    expect(labels.slice(0, 2)).toEqual(['E01', 'E02'])
    expect(labels[11]).toBe('Anime.Show.S01E12.Homecoming.BluRay.x264-GRP.mkv')
  })
})

describe('sorting', () => {
  it("puts a column's errors first, then its warnings, in episode order within one status", () => {
    const { resolution, items } = anime()
    const columns = resolution.columns ?? []
    const byA2 = sortRows(items, columns, at(columns, 'A2'), 1)
    expect(byA2.map((item) => item.label).slice(0, 3)).toEqual(['E11', 'E01', 'E02'])
    const byS1 = sortRows(items, columns, at(columns, 'S1'), 1)
    expect(byS1[0]?.label).toBe('E11')
    const descending = sortRows(items, columns, at(columns, 'A2'), -1)
    expect(descending.at(-1)?.label).toBe('E11')
  })

  it('keeps episode order without a column, reversed when descending', () => {
    const { resolution, items } = anime()
    const columns = resolution.columns ?? []
    expect(sortRows(items, columns, null, 1).map((item) => item.label)).toEqual(
      items.map((item) => item.label),
    )
    expect(sortRows(items, columns, null, -1)[0]?.label).toBe('E12')
  })

  it("ranks the name column by the row's output-name issues and a row without a job first", () => {
    const row = anime().resolution.rows?.[0] as Resolution
    const name = column('Output name')
    expect(cellRank(row, name)).toBe(3)
    const colliding: Resolution = {
      ...row,
      issues: [
        ...(row.issues ?? []),
        { severity: 'error', code: 'batch.name_collision', path: 'output.path', message: 'x' },
      ],
    }
    expect(cellRank(colliding, name)).toBe(0)
    expect(cellRank({ ...row, job: null }, column('A1'))).toBe(0)
  })
})

describe('pickedByHand', () => {
  it("sees an operation on the rule's selector, and no other rule's", () => {
    const ops = [{ op: 'replace' as const, path: '/audio_rules/1/selector/stream', value: 3 }]
    expect(pickedByHand(ops, 'audio', 1)).toBe(true)
    expect(pickedByHand(ops, 'audio', 0)).toBe(false)
    expect(pickedByHand(ops, 'subtitle', 1)).toBe(false)
    expect(
      pickedByHand(
        [{ op: 'replace', path: '/audio_rules/1/settings/bitrate', value: 3 }],
        'audio',
        1,
      ),
    ).toBe(false)
    expect(pickedByHand(undefined, 'audio', 1)).toBe(false)
  })
})

describe('trackText', () => {
  it('names a track by its absolute stream index', () => {
    const e05 = animeSources()[4]?.source
    expect(trackText(e05?.audio?.[2] as never)).toBe('#3 · eng · AC-3 2.0 · Commentary')
    expect(trackText(e05?.subtitles?.[0] as never)).toMatch(/^#4 · eng · /)
  })
})
