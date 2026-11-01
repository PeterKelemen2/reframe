import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, problem, settle } from '@/api/testing/fakes'
import type { MediaSource, TaskInfo } from '@/api/types'
import { probedSource } from '@/components/tracks/testing'

import { useScansStore } from './scans'
import { useSourcesStore } from './sources'
import { TaskLostError, useTasksStore } from './tasks'
import { useToastStore } from './toasts'

const SOURCE = 'src-1'
const BITRATE = `POST /api/sources/${SOURCE}/streams/1/bitrate-scan`
const SUBTITLES = `POST /api/sources/${SOURCE}/subtitle-scan`
const LOUDNESS = `POST /api/sources/${SOURCE}/streams/1/loudness`
const GET = `GET /api/sources/${SOURCE}`

// Unique across the tests: an event of an earlier test must not end a task of a later one.
let started = 0

function measured(): MediaSource {
  const source = probedSource('dts-hd-ma')
  source.audio![0]!.bitrate = { value: 2_140_063, source: 'measured' }
  return source
}

class ScanServer extends FakeServer {
  taskIds: string[] = []
  answer: MediaSource = measured()

  constructor() {
    super()
    const start = () => {
      const id = `scan-${++started}`
      this.taskIds.push(id)
      return { task_id: id }
    }
    this.on(BITRATE, start)
      .on(SUBTITLES, start)
      .on(LOUDNESS, start)
      .on(GET, () => this.answer)
  }

  last(): string {
    const id = this.taskIds.at(-1)
    if (id === undefined) throw new Error('no task yet')
    return id
  }

  end(task: Partial<TaskInfo> & Pick<TaskInfo, 'state'>, id = this.last()): void {
    useTasksStore().onTaskDone({ type: 'task.done', task: { id, kind: 'scan', ...task } })
  }

  progress(percent: number | null, id = this.last()): void {
    useTasksStore().onTaskProgress({
      type: 'task.progress',
      task: { id, kind: 'scan', state: 'running', progress: percent },
    })
  }
}

async function runsShown(count = 1): Promise<void> {
  await vi.waitFor(() => expect(useScansStore().runs).toHaveLength(count))
}

const bitrate = () => useSourcesStore().entries[0]?.source?.audio?.[0]?.bitrate
const toasts = () =>
  useToastStore().items.map(({ severity, summary, detail }) => ({ severity, summary, detail }))

describe('the scans store', () => {
  let server: ScanServer

  beforeEach(() => {
    setActivePinia(createPinia())
    server = new ScanServer()
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
    useSourcesStore().entries = [
      { id: SOURCE, path: '/media/dts-hd-ma.mkv', source: probedSource('dts-hd-ma') },
    ]
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('measureBitrate', () => {
    it('shows the task’s progress, then reads the source again so the table shows the measured bitrate', async () => {
      const scans = useScansStore()
      const measuring = scans.measureBitrate(SOURCE, 1)
      await runsShown()
      expect(scans.running(SOURCE, 'bitrate', 1)).toMatchObject({
        taskId: server.last(),
        progress: null,
      })
      server.progress(40)
      await vi.waitFor(() => expect(scans.running(SOURCE, 'bitrate', 1)?.progress).toBe(0.4))
      expect(server.count(GET)).toBe(0)

      server.end({
        state: 'done',
        result: { bitrate: { value: 2_140_063, source: 'measured' } } as never,
      })
      await measuring
      expect(server.count(GET)).toBe(1)
      expect(bitrate()).toEqual({ value: 2_140_063, source: 'measured' })
      expect(scans.runs).toEqual([])
      expect(toasts()).toEqual([])
    })

    it('keeps the run until the source is read again, so the table never shows Measure in between', async () => {
      const answer = deferred<MediaSource>()
      server.on(GET, () => answer.promise)
      const scans = useScansStore()
      const measuring = scans.measureBitrate(SOURCE, 1)
      await runsShown()
      server.end({ state: 'done', result: { bitrate: { value: 1, source: 'measured' } } as never })
      await vi.waitFor(() => expect(server.count(GET)).toBe(1))
      expect(scans.running(SOURCE, 'bitrate', 1)).toBeDefined()
      answer.resolve(measured())
      await measuring
      expect(scans.runs).toEqual([])
    })

    it('starts one task for a second click on the same track, and another for another track', async () => {
      server.on(`POST /api/sources/${SOURCE}/streams/2/bitrate-scan`, () => ({ task_id: 'other' }))
      const scans = useScansStore()
      const first = scans.measureBitrate(SOURCE, 1)
      const again = scans.measureBitrate(SOURCE, 1)
      void scans.measureBitrate(SOURCE, 2)
      await runsShown(2)
      expect(server.count(BITRATE)).toBe(1)
      server.end({ state: 'done', result: { bitrate: { value: 1, source: 'measured' } } as never })
      await Promise.all([first, again])
    })

    it('says so when the track gave no bitrate', async () => {
      const measuring = useScansStore().measureBitrate(SOURCE, 1)
      await runsShown()
      server.end({
        state: 'done',
        result: { bitrate: { value: null, source: 'unknown' } } as never,
      })
      await measuring
      expect(toasts()).toEqual([
        {
          severity: 'warn',
          summary: 'No bitrate could be measured',
          detail: 'The track has no packets with a size and a time.',
        },
      ])
    })

    it('shows a failed task as a toast and leaves the source as it was', async () => {
      const before = bitrate()
      const measuring = useScansStore().measureBitrate(SOURCE, 1)
      await runsShown()
      server.end({ state: 'failed', error: 'The file cannot be read.' })
      await measuring
      expect(toasts()).toEqual([
        {
          severity: 'error',
          summary: 'The bitrate could not be measured',
          detail: 'The file cannot be read.',
        },
      ])
      expect(server.count(GET)).toBe(0)
      expect(bitrate()).toEqual(before)
      expect(useScansStore().runs).toEqual([])
    })

    it('ends a cancelled task quietly, without reading the source', async () => {
      const measuring = useScansStore().measureBitrate(SOURCE, 1)
      await runsShown()
      server.end({ state: 'cancelled' })
      await measuring
      expect(toasts()).toEqual([])
      expect(server.count(GET)).toBe(0)
      expect(useScansStore().runs).toEqual([])
    })

    it('shows a task the server forgot as a failure', async () => {
      vi.spyOn(useTasksStore(), 'wait').mockRejectedValue(new TaskLostError('gone'))
      await useScansStore().measureBitrate(SOURCE, 1)
      expect(toasts()).toEqual([
        expect.objectContaining({
          severity: 'error',
          summary: 'The bitrate could not be measured',
        }),
      ])
      expect(useScansStore().runs).toEqual([])
    })

    it('resolves without a run when the server refuses the scan', async () => {
      server.on(BITRATE, () => problem(404, 'source.unknown', 'No source src-1'))
      await useScansStore().measureBitrate(SOURCE, 1)
      expect(useScansStore().runs).toEqual([])
      expect(toasts()).toEqual([expect.objectContaining({ summary: 'No source src-1' })])
    })

    it('can be started again after a scan ended', async () => {
      const scans = useScansStore()
      const first = scans.measureBitrate(SOURCE, 1)
      await runsShown()
      server.end({ state: 'cancelled' })
      await first
      void scans.measureBitrate(SOURCE, 1)
      await runsShown()
      expect(server.count(BITRATE)).toBe(2)
    })
  })

  describe('scanSubtitles', () => {
    it('counts one track, then reads the source again', async () => {
      const scans = useScansStore()
      const counting = scans.scanSubtitles(SOURCE, [3])
      await runsShown()
      expect(server.requests.find((r) => `${r.method} ${r.path}` === SUBTITLES)?.body).toEqual({
        stream_indexes: [3],
      })
      expect(scans.running(SOURCE, 'subtitle', 3)).toBeDefined()
      server.end({ state: 'done', result: { tracks: [] } as never })
      await counting
      expect(server.count(GET)).toBe(1)
    })

    it('counts every track without stream indexes, as a run without a stream', async () => {
      const scans = useScansStore()
      void scans.scanSubtitles(SOURCE)
      await runsShown()
      expect(server.requests.at(-1)?.body).toEqual({ stream_indexes: null })
      expect(scans.running(SOURCE, 'subtitle')).toBeDefined()
    })

    it('joins the scan of every track instead of counting one track again', async () => {
      const scans = useScansStore()
      const all = scans.scanSubtitles(SOURCE)
      const one = scans.scanSubtitles(SOURCE, [3])
      await runsShown()
      expect(server.count(SUBTITLES)).toBe(1)
      server.end({ state: 'done', result: { tracks: [] } as never })
      await Promise.all([all, one])
    })
  })

  describe('measureLoudness', () => {
    it('keeps the measurement by source and stream, and does not read the source again', async () => {
      const scans = useScansStore()
      const measuring = scans.measureLoudness(SOURCE, 1)
      await runsShown()
      const result = {
        path: '/media/dts-hd-ma.mkv',
        stream_index: 1,
        integrated: -22.47,
        true_peak: -20,
        lra: 2.2,
      }
      server.end({ state: 'done', result: result as never })
      expect(await measuring).toEqual(result)
      expect(scans.loudness[`${SOURCE}:1`]).toEqual(result)
      expect(server.count(GET)).toBe(0)
    })

    it('gives null for a failed measurement', async () => {
      const measuring = useScansStore().measureLoudness(SOURCE, 1)
      await runsShown()
      server.end({ state: 'failed', error: 'Stream 1 is not an audio stream.' })
      expect(await measuring).toBeNull()
      expect(useScansStore().loudness).toEqual({})
      expect(toasts()[0]?.summary).toBe('The loudness could not be measured')
    })
  })

  describe('cancel', () => {
    it('asks the server to cancel the run’s task', async () => {
      const scans = useScansStore()
      void scans.measureBitrate(SOURCE, 1)
      await runsShown()
      const taskId = server.last()
      server.on(`POST /api/tasks/${taskId}/cancel`, { cancelled: true })
      await scans.cancel(scans.runs[0]!)
      expect(server.count(`POST /api/tasks/${taskId}/cancel`)).toBe(1)
      await settle()
    })
  })
})
