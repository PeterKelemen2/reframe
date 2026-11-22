import { createPinia, setActivePinia } from 'pinia'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { boot, shutdown } from '@/api/boot'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { http } from '@/api/testing/serverHelpers'
import type { MediaSource, SourceEntry } from '@/api/types'
import { makeCommentaryFile } from '@/components/media/testing/media.mjs'
import { pinnedTools } from '@/editor/testing/tools.mjs'

import { useScansStore } from './scans'
import { useSourcesStore } from './sources'
import { useToastStore } from './toasts'

const PORT = 8721
const TOKEN = 'scans-test-token'

let server: DevServer

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: [
      '--token',
      TOKEN,
      '--fixtures',
      'dts-hd-ma,pgs',
      ...(tools === null ? [] : ['--tools-dir', tools]),
    ],
  })
  makeCommentaryFile(`${server.media}/commentary.mkv`)
}, 180_000)

afterAll(async () => {
  await server.stop()
})

beforeEach(async () => {
  setActivePinia(createPinia())
  await boot({ backend: async () => ({ baseUrl: server.url }), token: TOKEN })
})

afterEach(() => {
  shutdown()
})

async function opened(name: string): Promise<SourceEntry> {
  const [entry] = await useSourcesStore().open([`${server.media}/${name}`])
  if (entry?.source === null || entry === undefined) throw new Error(`${name} did not open`)
  return entry
}

function entryOf(id: string): MediaSource {
  const source = useSourcesStore().entries.find((entry) => entry.id === id)?.source
  if (source === null || source === undefined) throw new Error(`no source ${id}`)
  return source
}

describe('the scans against a real server', () => {
  it('measures the DTS-HD MA track, and the source read again holds it as measured', async () => {
    const { id } = await opened('dts-hd-ma.mkv')
    // The file has no rate: the probe samples its clusters (one cluster in this short file).
    expect(entryOf(id).audio?.[0]?.bitrate).toEqual({
      value: 2_139_528,
      source: 'estimated',
      samples: 1,
    })
    const scans = useScansStore()
    await scans.measureBitrate(id, 1)
    const bitrate = entryOf(id).audio?.[0]?.bitrate
    expect(bitrate?.source).toBe('measured')
    // Measured from the fixture's packets: testdata/README.md has the bytes and the duration.
    expect(bitrate?.value).toBe(2_140_063)
    expect(scans.runs).toEqual([])
    expect(useToastStore().items).toEqual([])
    const kept = await http<MediaSource>(server, 'GET', `/api/sources/${id}`)
    expect(kept.audio?.[0]?.bitrate).toEqual(bitrate)
  })

  it('counts the events and forced events of the PGS tracks', async () => {
    const { id } = await opened('pgs.mkv')
    await useScansStore().scanSubtitles(id)
    expect(
      entryOf(id).subtitles?.map((track) => [
        track.index,
        track.event_count,
        track.event_count_source,
        track.forced_event_count,
      ]),
    ).toEqual([
      [1, 12, 'measured', 2],
      [2, 4, 'measured', 2],
    ])
  })

  it('measures the loudness of an audio track, which the source does not keep', async () => {
    const { id } = await opened('dts-hd-ma.mkv')
    const scans = useScansStore()
    const measured = await scans.measureLoudness(id, 1)
    expect(measured).toMatchObject({
      stream_index: 1,
      integrated: -22.47,
      true_peak: -20,
      lra: 2.2,
    })
    expect(scans.loudness[`${id}:1`]).toEqual(measured)
  })

  it('cancels a measurement quietly and leaves the track as it was; a later one replaces the estimate', async () => {
    const { id } = await opened('commentary.mkv')
    const before = entryOf(id).audio?.[1]
    expect(before?.bitrate).toMatchObject({ source: 'estimated', samples: 32 })
    // A 2.0 track under 192 kb/s after a 5.1 track in its language is marked as commentary.
    expect(before?.roles?.map((role) => [role.role, role.evidence])).toEqual([
      ['commentary', 'heuristic'],
    ])

    const scans = useScansStore()
    const measuring = scans.measureBitrate(id, 1)
    await vi.waitFor(() => expect(scans.running(id, 'bitrate', 1)).toBeDefined())
    await scans.cancel(scans.running(id, 'bitrate', 1)!)
    await measuring
    expect(scans.runs).toEqual([])
    expect(useToastStore().items).toEqual([])
    expect(entryOf(id).audio?.[1]).toEqual(before)

    await scans.measureBitrate(id, 1)
    const after = entryOf(id).audio?.[1]
    expect(after?.bitrate).toMatchObject({ source: 'measured' })
    expect(after?.bitrate?.samples ?? null).toBeNull()
    expect(after?.roles).toEqual(before?.roles)
  })
})
