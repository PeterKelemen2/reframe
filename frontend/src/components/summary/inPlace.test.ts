import { describe, expect, it } from 'vitest'

import type { MediaSource, ValidationIssue } from '@/api/types'

import { inPlaceIssues, isMatroska } from './inPlace'
import { multitrackSource } from './testing'

function source(path: string, formatName: string | null): MediaSource {
  const base = multitrackSource()
  return {
    ...base,
    ref: { ...base.ref, path },
    container: { ...base.container, format_name: formatName },
  } as MediaSource
}

function issue(code: string, path: string): ValidationIssue {
  return { severity: 'error', code, path, message: code, fixes: [] }
}

describe('what can be edited in place', () => {
  it('is a Matroska file, and not a WebM file, which ffprobe names the same', () => {
    expect(isMatroska(source('/media/a.mkv', 'matroska,webm'))).toBe(true)
    expect(isMatroska(source('/media/a.WEBM', 'matroska,webm'))).toBe(false)
    expect(isMatroska(source('/media/a.mp4', 'mov,mp4,m4a,3gp,3g2,mj2'))).toBe(false)
    expect(isMatroska(source('/media/a.mkv', null))).toBe(false)
  })

  it('has its issues: the inplace ones, and no others', () => {
    const issues = [
      issue('inplace.not_possible', 'output.edit_in_place'),
      issue('inplace.output_ignored', 'output.path'),
      issue('output.same_as_source', 'output.path'),
      issue('encoder.unavailable', 'video.encoder'),
    ]
    expect(inPlaceIssues(issues).map((found) => found.code)).toEqual([
      'inplace.not_possible',
      'inplace.output_ignored',
    ])
  })
})
