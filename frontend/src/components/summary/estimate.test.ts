import { describe, expect, it } from 'vitest'

import type { JobSettings } from '@/api/types'
import { sampleJob } from '@/editor/testing/samples'

import { estimateSize, jobDuration } from './estimate'
import { multitrackSource, sampleDefinitions } from './testing'

const DEFINITIONS = sampleDefinitions()
/** multitrack.mkv's duration. */
const SECONDS = 4.021

function bitrateJob(kbps = 6000): JobSettings {
  const job = sampleJob()
  job.video!.rate_control = { mode: 'bitrate', kbps, two_pass: false, turbo_first_pass: false }
  return job
}

function bytes(kbps: number, seconds = SECONDS): number {
  return (kbps * 1000 * seconds) / 8
}

describe('the size estimate', () => {
  it('depends on content in constant quality mode', () => {
    expect(estimateSize(sampleJob(), multitrackSource(), DEFINITIONS)).toEqual({ kind: 'quality' })
  })

  it('is the video and audio bitrates times the duration in bitrate mode', () => {
    const estimate = estimateSize(bitrateJob(), multitrackSource(), DEFINITIONS)
    // Three AAC tracks at 160 kb/s.
    expect(estimate).toMatchObject({
      kind: 'size',
      videoKbps: 6000,
      audioKbps: 480,
      unknownTracks: 0,
    })
    expect(estimate.kind === 'size' && estimate.bytes).toBeCloseTo(bytes(6480))
  })

  it("takes the encoder's default bitrate for the mixdown, or for the source's layout", () => {
    const job = bitrateJob()
    job.audio![0]!.bitrate = null
    job.audio![1]!.bitrate = null
    job.audio![1]!.mixdown = null
    job.audio!.splice(2, 1)
    const estimate = estimateSize(job, multitrackSource(), DEFINITIONS)
    // Stereo: 160; the 2-channel source kept: stereo, 160.
    expect(estimate).toMatchObject({ audioKbps: 320, unknownTracks: 0 })
    job.audio![1]!.source_stream = 1
    // The 5.1 source kept: 384.
    expect(estimateSize(job, multitrackSource(), DEFINITIONS)).toMatchObject({ audioKbps: 544 })
  })

  it("counts a copied track at the source's bitrate, and leaves out one whose bitrate is unknown", () => {
    const job = bitrateJob()
    job.audio![0]!.action = 'passthru'
    job.audio![1]!.action = 'passthru'
    const estimate = estimateSize(job, multitrackSource(), DEFINITIONS)
    // Track 1 (AC-3) is 192 kb/s in the file; track 2 has no bitrate; track 3 encodes at 160.
    expect(estimate).toMatchObject({ audioKbps: 352, unknownTracks: 1 })
  })

  it('leaves out tracks with a VBR quality or a lossless encoder', () => {
    const job = bitrateJob()
    job.audio![0]!.bitrate = null
    job.audio![0]!.quality = 4
    job.audio![1]!.encoder = 'flac'
    job.audio![1]!.bitrate = null
    expect(estimateSize(job, multitrackSource(), DEFINITIONS)).toMatchObject({
      audioKbps: 160,
      unknownTracks: 2,
    })
  })

  it("counts a copied video at the source's bitrate, and cannot estimate it without one", () => {
    const job = sampleJob()
    job.video!.passthrough = true
    expect(estimateSize(job, multitrackSource(), DEFINITIONS)).toEqual({
      kind: 'unknown',
      reason: 'video',
    })
    const source = multitrackSource()
    source.video![0]!.bitrate = { value: 500_000, source: 'stream' }
    expect(estimateSize(job, source, DEFINITIONS)).toMatchObject({ kind: 'size', videoKbps: 500 })
  })

  it('cannot estimate a source without a duration', () => {
    const source = multitrackSource()
    source.container!.duration = null
    expect(estimateSize(bitrateJob(), source, DEFINITIONS)).toEqual({
      kind: 'unknown',
      reason: 'duration',
    })
  })
})

describe("the duration of a job's range", () => {
  it('is the part of the source the range covers', () => {
    const job = sampleJob()
    const source = multitrackSource()
    expect(jobDuration(job, source)).toBe(SECONDS)
    job.range = { kind: 'time', start: 1, end: 3 }
    expect(jobDuration(job, source)).toBe(2)
    job.range = { kind: 'time', start: 1, end: null }
    expect(jobDuration(job, source)).toBeCloseTo(SECONDS - 1)
    job.range = { kind: 'frames', start: 25, end: 75 }
    expect(jobDuration(job, source)).toBe(2)
    source.chapters = [
      { index: 0, start: 0, end: 1.5 },
      { index: 1, start: 1.5, end: 3 },
      { index: 2, start: 3, end: SECONDS },
    ]
    job.range = { kind: 'chapters', start: 2, end: 3 }
    expect(jobDuration(job, source)).toBeCloseTo(SECONDS - 1.5)
  })

  it('stops at the end of the source, so the size is not estimated for frames never encoded', () => {
    const job = bitrateJob()
    const source = multitrackSource()
    source.chapters = [
      { index: 0, start: 0, end: 2 },
      { index: 1, start: 2, end: SECONDS },
    ]
    job.range = { kind: 'time', start: 1, end: 600 }
    expect(jobDuration(job, source)).toBeCloseTo(SECONDS - 1)
    job.range = { kind: 'chapters', start: 2, end: 9 }
    expect(jobDuration(job, source)).toBeCloseTo(SECONDS - 2)
    // 4.021 s at 25 fps: 101 frames.
    job.range = { kind: 'frames', start: 25, end: 100_000 }
    expect(jobDuration(job, source)).toBeCloseTo(76 / 25)
    expect(estimateSize(job, multitrackSource(), DEFINITIONS)).toMatchObject({
      kind: 'size',
      seconds: 76 / 25,
    })
  })
})
