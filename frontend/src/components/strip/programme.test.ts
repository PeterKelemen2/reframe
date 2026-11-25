import { describe, expect, it } from 'vitest'

import type { JobSettings } from '@/api/types'
import { languageSlot, slotColor } from '@/components/base/languageColor'
import { languages } from '@/components/language/testing'
import { chaptersSource } from '@/components/range/testing'
import { multitrackSource, sampleDefinitions } from '@/components/summary/testing'
import { sampleJob } from '@/editor/testing/samples'

import {
  buildLanes,
  chapterSegments,
  clockText,
  percentAt,
  type Tick,
  ticks,
  tickStep,
} from './programme'

const LANGUAGES = languages()

function lanesOf(job: JobSettings, preferred: string[] = ['hu', 'en']) {
  return buildLanes(job, multitrackSource(), {
    definitions: sampleDefinitions(),
    languages: LANGUAGES,
    colorOf: (tag) => slotColor(languageSlot(tag, LANGUAGES, preferred)),
    passthru: 'passthru',
  })
}

function majors(found: Tick[]): number[] {
  return found.filter((tick) => tick.major).map((tick) => tick.seconds)
}

describe('the ruler', () => {
  it('steps by seconds on a short clip, ten minutes on an hour, half an hour on three', () => {
    expect(tickStep(10, 6)).toBe(2)
    expect(tickStep(4, 6)).toBe(1)
    expect(tickStep(3600, 6)).toBe(600)
    expect(tickStep(57 * 60 + 41, 6)).toBe(600)
    expect(tickStep(3 * 3600, 6)).toBe(1800)
  })

  it('takes a finer step when the strip has room for more labels', () => {
    expect(tickStep(3600, 12)).toBe(300)
    expect(tickStep(3600, 2)).toBe(1800)
    expect(tickStep(1.5, 6)).toBe(0.5)
  })

  it('labels every step from the start and marks the half steps between them', () => {
    const found = ticks(57 * 60 + 41, 600)
    expect(majors(found)).toEqual([0, 600, 1200, 1800, 2400, 3000])
    expect(found.filter((tick) => !tick.major).map((tick) => tick.seconds)).toEqual([
      300, 900, 1500, 2100, 2700, 3300,
    ])
    expect(majors(ticks(0.6, 0.2))).toEqual([0, 0.2, 0.4, 0.6])
  })

  it('writes times as m:ss or h:mm:ss, with tenths when asked', () => {
    expect(clockText(0)).toBe('0:00')
    expect(clockText(3461)).toBe('57:41')
    expect(clockText(5400)).toBe('1:30:00')
    expect(clockText(2.04, true)).toBe('0:02.0')
    expect(clockText(0.25, true)).toBe('0:00.3')
  })

  it('places a time in percent of the programme, inside it', () => {
    expect(percentAt(30, 120)).toBe(25)
    expect(percentAt(200, 120)).toBe(100)
    expect(percentAt(5, 0)).toBe(0)
  })
})

describe('the chapter row', () => {
  it('numbers the source chapters', () => {
    const segments = chapterSegments(sampleJob(), chaptersSource(), 5.021)
    expect(segments.map((segment) => [segment.number, segment.start, segment.end])).toEqual([
      [1, 0, 1],
      [2, 1, 2.5],
      [3, 2.5, 4],
      [4, 4, 5],
    ])
    expect(segments[0]!.title).toBe('Opening')
  })

  it('shows the chapters the job generates when the source has none', () => {
    const job = sampleJob()
    job.chapters = { enabled: true, names: null, generate_every: 5 }
    const segments = chapterSegments(job, multitrackSource(), 12 * 60)
    expect(segments.map((segment) => [segment.start, segment.end])).toEqual([
      [0, 300],
      [300, 600],
      [600, 720],
    ])
  })

  it('has no row without chapters', () => {
    expect(chapterSegments(sampleJob(), multitrackSource(), 4)).toEqual([])
    const job = sampleJob()
    job.chapters = { enabled: false, names: null, generate_every: 5 }
    expect(chapterSegments(job, multitrackSource(), 600)).toEqual([])
  })
})

describe('the lanes', () => {
  it('has one lane per output track: audio, then subtitles, in output order', () => {
    const job = sampleJob()
    job.audio = [job.audio![2]!, job.audio![0]!]
    const lanes = lanesOf(job)
    expect(lanes.map((lane) => [lane.path, lane.kind, lane.number, lane.code])).toEqual([
      ['audio[0]', 'audio', 1, 'en'],
      ['audio[1]', 'audio', 2, 'ja'],
      ['subtitles[0]', 'subtitle', 1, 'en'],
    ])
  })

  it('colours a lane by its language slot, the preferred languages first', () => {
    const job = sampleJob()
    job.audio![0]!.metadata!.language = 'hu'
    const [hungarian, english] = lanesOf(job, ['hu', 'en'])
    expect(hungarian!.color).toBe('var(--rf-lang-1)')
    expect(english!.color).toBe('var(--rf-lang-2)')
    expect(lanesOf(job, ['en', 'hu'])[0]!.color).toBe('var(--rf-lang-2)')
    expect(hungarian!.languageName).toBe('Hungarian')
  })

  it('draws a commentary track pale, as its output flag says', () => {
    const job = sampleJob()
    expect(lanesOf(job).map((lane) => lane.commentary)).toEqual([false, false, true, false])
    job.audio![2]!.metadata!.commentary = false
    expect(lanesOf(job)[2]!.commentary).toBe(false)
  })

  it('marks a burned-in subtitle and one with only its forced events', () => {
    const job = sampleJob()
    job.subtitles = [
      { ...job.subtitles![0]!, action: 'burn' },
      { ...job.subtitles![0]!, source: 6, forced_only: true },
    ]
    const [burned, forced] = lanesOf(job).slice(3)
    expect([burned!.burn, burned!.forcedOnly]).toEqual([true, false])
    expect([forced!.burn, forced!.forcedOnly]).toEqual([false, true])
  })

  it('names the codec each track is written in', () => {
    const job = sampleJob()
    job.audio![1]!.action = 'passthru'
    const lanes = lanesOf(job)
    expect(lanes[0]!.format).toBe('AAC Stereo')
    expect(lanes[1]!.format).toContain('passthru')
    expect(lanes[3]!.format).toBe('SRT')
  })

  it('draws an undetermined language in the neutral colour', () => {
    const job = sampleJob()
    job.audio![0]!.metadata!.language = 'und'
    const [lane] = lanesOf(job)
    expect([lane!.code, lane!.languageName, lane!.color]).toEqual([
      'und',
      null,
      'var(--rf-lang-und)',
    ])
  })
})
