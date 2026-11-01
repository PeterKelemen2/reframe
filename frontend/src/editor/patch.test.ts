import { describe, expect, it } from 'vitest'

import type { JsonPatchOp } from '@/api/types'

import { applyOps, diffJson, PatchError, sameJson } from './patch'

describe('applyOps', () => {
  it('applies every operation to a frozen copy and leaves the input alone', () => {
    const document = { video: { encoder: 'libx265' }, audio: [{ bitrate: 160 }] }
    const result = applyOps(document, [
      { op: 'replace', path: '/video/encoder', value: 'libx264' },
      { op: 'add', path: '/audio/-', value: { bitrate: 96 } },
    ])
    expect(result).toEqual({
      video: { encoder: 'libx264' },
      audio: [{ bitrate: 160 }, { bitrate: 96 }],
    })
    expect(document).toEqual({ video: { encoder: 'libx265' }, audio: [{ bitrate: 160 }] })
    expect(Object.isFrozen(result.audio[1])).toBe(true)
    expect(() => {
      ;(result.video as { encoder: string }).encoder = 'x'
    }).toThrow(TypeError)
  })

  it('applies none of a patch when one operation fails', () => {
    const document = { video: { encoder: 'libx265', preset: 'slow' } }
    const ops: JsonPatchOp[] = [
      { op: 'replace', path: '/video/encoder', value: 'libx264' },
      { op: 'replace', path: '/video/missing/deep', value: 1 },
    ]
    let thrown: unknown
    try {
      applyOps(document, ops)
    } catch (error) {
      thrown = error
    }
    expect(thrown).toBeInstanceOf(PatchError)
    expect((thrown as PatchError).op).toBe(ops[1])
    expect(document.video.encoder).toBe('libx265')
  })

  it('fails a test operation that does not hold', () => {
    expect(() =>
      applyOps({ a: 1 }, [
        { op: 'test', path: '/a', value: 2 },
        { op: 'replace', path: '/a', value: 3 },
      ]),
    ).toThrow(PatchError)
  })

  it('replaces the whole document', () => {
    expect(applyOps({ a: 1 }, [{ op: 'replace', path: '', value: { b: 2 } }])).toEqual({ b: 2 })
  })
})

describe('diffJson', () => {
  it.each([
    ['a key removed and added again', { a: 1, b: 2, c: 3 }, { a: 1, c: 3, b: 2 }],
    ['a key added before others', { b: 2 }, { a: 1, b: 2 }],
    [
      'nested filters reordered',
      { f: { x: { p: 1 }, y: { p: 2 } } },
      { f: { y: { p: 2 }, x: { p: 1 } } },
    ],
    ['a member changes its type', { v: { mode: 'quality' } }, { v: null }],
  ])('turns one document into the other with its key order: %s', (_name, before, after) => {
    const result = applyOps(before, diffJson(before, after))
    expect(JSON.stringify(result)).toBe(JSON.stringify(after))
  })

  it('is empty for equal documents', () => {
    expect(diffJson({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] })).toEqual([])
  })
})

describe('sameJson', () => {
  it('ignores key order and sees any other difference', () => {
    expect(sameJson({ a: 1, b: [1] }, { b: [1], a: 1 })).toBe(true)
    expect(sameJson({ a: 1 }, { a: 1, b: null })).toBe(false)
  })
})
