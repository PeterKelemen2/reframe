import { describe, expect, it } from 'vitest'

import type { JobSettings, JsonPatchOp } from '@/api/types'

import {
  changesTrackList,
  inJob,
  mergedResolutions,
  mergeOverride,
  ordered,
  perFileChange,
  perFilePointer,
  sectionsOf,
  withoutOps,
} from './group'
import { applyOps } from './patch'
import { sampleJob } from './testing/samples'

function changed(ops: JsonPatchOp[]): string | null {
  const job = sampleJob()
  return perFileChange(job, applyOps(job, ops))
}

const external = {
  action: 'copy',
  convert_to: null,
  forced_only: false,
  source: { path: '/media/movie.en.srt', format: 'srt' },
  metadata: sampleJob().subtitles?.[0]?.metadata,
}

describe('perFileChange', () => {
  it.each<[string, JsonPatchOp[], string | null]>([
    [
      'the range',
      [{ op: 'replace', path: '/range', value: { kind: 'chapters', start: 1, end: 2 } }],
      'range',
    ],
    [
      'the output path',
      [{ op: 'replace', path: '/output/path', value: '/out/x.mkv' }],
      'outputPath',
    ],
    [
      'edit in place',
      [{ op: 'replace', path: '/output/edit_in_place', value: true }],
      'editInPlace',
    ],
    [
      'a manual name',
      [{ op: 'replace', path: '/output/naming/manual_name', value: 'X' }],
      'manualName',
    ],
    [
      'a name correction',
      [{ op: 'add', path: '/output/naming/field_overrides/episode', value: '5' }],
      'nameFields',
    ],
    [
      'the video metadata',
      [{ op: 'replace', path: '/video/metadata/language', value: 'ja' }],
      'videoMetadata',
    ],
    [
      'own chapter names',
      [{ op: 'replace', path: '/chapters/names', value: ['Intro', 'Part A'] }],
      'chapterNames',
    ],
    [
      'an external subtitle',
      [{ op: 'add', path: '/subtitles/-', value: external }],
      'externalSubtitle',
    ],
    [
      'the whole output',
      [{ op: 'replace', path: '/output', value: { container: 'mp4' } }],
      'outputPath',
    ],
    ['the preset', [{ op: 'replace', path: '/preset_id', value: 'h264' }], 'preset'],
    [
      'generated chapter names',
      [{ op: 'replace', path: '/chapters/names', value: ['Chapter 1', 'Chapter 2'] }],
      null,
    ],
    ['an audio bitrate', [{ op: 'replace', path: '/audio/0/bitrate', value: 448 }], null],
    [
      'the naming template',
      [{ op: 'replace', path: '/output/naming/template', value: '{name}' }],
      null,
    ],
    ['the container', [{ op: 'replace', path: '/output/container', value: 'mp4' }], null],
  ])('%s', (_name, ops, field) => {
    expect(changed(ops)).toBe(field)
  })

  it('takes names back to the source names', () => {
    const job = applyOps(sampleJob(), [
      { op: 'replace', path: '/chapters/names', value: ['Intro'] },
    ])
    expect(
      perFileChange(job, applyOps(job, [{ op: 'replace', path: '/chapters/names', value: null }])),
    ).toBeNull()
  })
})

describe('perFilePointer', () => {
  it('knows the per-file fields, below them too, and external subtitles', () => {
    const job = applyOps(sampleJob(), [{ op: 'add', path: '/subtitles/-', value: external }])
    expect(perFilePointer('/chapters/names/2', job)).toBe(true)
    expect(perFilePointer('/video/metadata/language', job)).toBe(true)
    expect(perFilePointer('/subtitles/1/metadata/name', job)).toBe(true)
    expect(perFilePointer('/subtitles/0/metadata/name', job)).toBe(false)
    expect(perFilePointer('/audio/1/bitrate', job)).toBe(false)
    expect(perFilePointer('/output/container', job)).toBe(false)
  })
})

describe('sectionsOf', () => {
  it('names the derive sections and the output options', () => {
    expect(
      sectionsOf([
        { op: 'replace', path: '/audio/0/bitrate', value: 1 },
        { op: 'replace', path: '/subtitles/0/metadata/forced', value: true },
        { op: 'replace', path: '/output/naming/template', value: 'x' },
      ]),
    ).toEqual({ sections: ['audio', 'subtitles', 'naming'], output: false })
    expect(sectionsOf([{ op: 'replace', path: '/output/container', value: 'mp4' }])).toEqual({
      sections: [],
      output: true,
    })
    expect(sectionsOf([{ op: 'replace', path: '/output/path', value: 'x' }]).output).toBe(false)
  })
})

describe('changesTrackList', () => {
  it.each<[JsonPatchOp, boolean]>([
    [{ op: 'add', path: '/audio/-', value: {} }, true],
    [{ op: 'add', path: '/audio/1', value: {} }, true],
    [{ op: 'remove', path: '/subtitles/0' }, true],
    [{ op: 'move', from: '/audio/2', path: '/audio/0' }, true],
    [{ op: 'replace', path: '/audio', value: [] }, true],
    [{ op: 'replace', path: '/audio/1', value: {} }, false],
    [{ op: 'replace', path: '/audio/1/bitrate', value: 1 }, false],
    [{ op: 'test', path: '/audio/1', value: {} }, false],
  ])('%j → %s', (op, structural) => {
    expect(changesTrackList(op)).toBe(structural)
  })
})

describe('mergeOverride', () => {
  const job: JobSettings = sampleJob()

  it('guards an operation inside an output track with a test of the whole track, after the unguarded ones', () => {
    const merged = mergeOverride(
      [],
      [
        { op: 'replace', path: '/audio/1/bitrate', value: 320 },
        { op: 'replace', path: '/video/encoder', value: 'libx264' },
        { op: 'replace', path: '/subtitles/0/metadata/forced', value: true },
      ].map((op) => inJob(op as JsonPatchOp)),
      job,
    )
    expect(merged).toEqual([
      { op: 'replace', path: '/job/video/encoder', value: 'libx264' },
      { op: 'test', path: '/job/audio/1', value: job.audio?.[1] },
      { op: 'replace', path: '/job/audio/1/bitrate', value: 320 },
      { op: 'test', path: '/job/subtitles/0', value: job.subtitles?.[0] },
      { op: 'replace', path: '/job/subtitles/0/metadata/forced', value: true },
    ])
  })

  it('replaces an earlier operation on the same path or below it, and keeps the first guard', () => {
    const first = mergeOverride(
      [],
      [inJob({ op: 'replace', path: '/audio/1/bitrate', value: 320 })],
      job,
    )
    // The job now has the override: the guard stays the track without it.
    const overridden = applyOps(job, [{ op: 'replace', path: '/audio/1/bitrate', value: 320 }])
    const merged = mergeOverride(
      first,
      [inJob({ op: 'replace', path: '/audio/1', value: { bitrate: 96 } })],
      overridden,
    )
    expect(merged).toEqual([
      { op: 'test', path: '/job/audio/1', value: job.audio?.[1] },
      { op: 'replace', path: '/job/audio/1', value: { bitrate: 96 } },
    ])
  })

  it('leaves out a test of the edit itself', () => {
    const merged = mergeOverride(
      [],
      [
        inJob({ op: 'test', path: '/video/encoder', value: 'libx265' }),
        inJob({ op: 'replace', path: '/video/encoder', value: 'libx264' }),
      ],
      job,
    )
    expect(merged).toEqual([{ op: 'replace', path: '/job/video/encoder', value: 'libx264' }])
  })
})

describe('ordered', () => {
  it('puts each rule’s selector guard before its pick, after the unguarded operations', () => {
    const guard: JsonPatchOp = { op: 'test', path: '/audio_rules/1/selector', value: {} }
    const pick: JsonPatchOp = { op: 'replace', path: '/audio_rules/1/selector/stream', value: 3 }
    const name: JsonPatchOp = {
      op: 'add',
      path: '/job/output/naming/field_overrides/episode',
      value: '5',
    }
    expect(ordered([guard, pick, name])).toEqual([name, guard, pick])
    expect(ordered([guard])).toEqual([])
  })
})

describe('withoutOps', () => {
  it('drops the guards left without an operation', () => {
    const override = mergeOverride(
      [{ op: 'replace', path: '/audio_rules/0/selector/stream', value: 3 }],
      [inJob({ op: 'replace', path: '/audio/1/bitrate', value: 320 })],
      sampleJob(),
    )
    expect(withoutOps(override, (op) => op.path === '/job/audio/1/bitrate')).toEqual([
      { op: 'replace', path: '/audio_rules/0/selector/stream', value: 3 },
    ])
  })
})

function row(path: string) {
  return { path, status: 'ok' as const }
}

describe('mergedResolutions', () => {
  it('takes the first columns and every row and issue in order', () => {
    const issue = {
      severity: 'error' as const,
      code: 'batch.name_collision',
      path: '',
      message: 'x',
    }
    expect(
      mergedResolutions({
        grouping: { groups: [], issues: [] },
        resolutions: [
          {
            columns: [{ kind: 'video', label: 'V', defaults: false }],
            rows: [row('/a.mkv')],
            issues: [],
          },
          {
            columns: [{ kind: 'name', label: 'Output name', defaults: false }],
            rows: [row('/b.mkv')],
            issues: [issue],
          },
        ],
      }),
    ).toEqual({
      group: null,
      columns: [{ kind: 'video', label: 'V', defaults: false }],
      rows: [row('/a.mkv'), row('/b.mkv')],
      issues: [issue],
    })
  })
})
