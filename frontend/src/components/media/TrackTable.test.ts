import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import type { AudioStream, SubtitleStream, TaskInfo } from '@/api/types'
import { mountBase } from '@/components/base/testing'
import { probedSource } from '@/components/tracks/testing'
import { type ScanKind, type ScanRun, useScansStore } from '@/stores/scans'
import { useTasksStore } from '@/stores/tasks'

import TrackTable from './TrackTable.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  vi.restoreAllMocks()
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

function mountTable(kind: 'audio' | 'subtitle', streams: unknown[]) {
  const wrapper = mountBase(TrackTable, { props: { kind, streams } })
  mounted.push(wrapper)
  return wrapper
}

function words(element: Element): string {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
  const parts: string[] = []
  while (walker.nextNode()) {
    const part = walker.currentNode.textContent?.replace(/\s+/g, ' ').trim()
    if (part) parts.push(part)
  }
  return parts.join(' ')
}

function cells(wrapper: VueWrapper, row: number): string[] {
  const rows = wrapper.findAll('.track-table__row')
  return rows[row]!.findAll('td').map((cell) => words(cell.element))
}

function detail(wrapper: VueWrapper, label: string): string | undefined {
  const pair = wrapper
    .findAll('.track-table__details .rf-kv')
    .find((candidate) => candidate.find('dt').text() === label)
  return pair && words(pair.find('dd').element)
}

/** Speech input users say what they see: a scan button's name starts with its visible text. */
function expectNamesStartWithText(wrapper: VueWrapper): void {
  const buttons = wrapper.findAll('[data-action="start-scan"]')
  expect(buttons.length).toBeGreaterThan(0)
  for (const found of buttons) {
    const name = (found.attributes('aria-label') ?? '').toLowerCase()
    const text = found.text().toLowerCase()
    expect(name.slice(0, text.length)).toBe(text)
  }
}

describe('the audio source table', () => {
  it('shows the columns of each track, with the bitrate and where it comes from', () => {
    const wrapper = mountTable('audio', probedSource('multitrack').audio!)
    expect(cells(wrapper, 0)).toEqual([
      '1',
      'jpn',
      'Japanese 5.1',
      'AC-3',
      '5.1',
      '48 kHz',
      '192 kb/s stream',
      'Main (Set by a disposition flag in the file) Default',
    ])
    expect(cells(wrapper, 1)[6]).toBe('— Unknown')
  })

  it('shows the bit depth of a lossless track', () => {
    const wrapper = mountTable('audio', probedSource('dts-hd-ma').audio!)
    expect(cells(wrapper, 0).slice(3, 7)).toEqual([
      'DTS-HD MA',
      '5.1',
      '48 kHz / 24-bit',
      '— Unknown',
    ])
  })

  it('expands a row to every detail and collapses it again', async () => {
    const wrapper = mountTable('audio', probedSource('multitrack').audio!)
    const toggle = wrapper.findAll('.track-table__toggle')[0]!
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    const details = wrapper.find('.track-table__details')
    expect(details.attributes('id')).toBe(toggle.attributes('aria-controls'))
    expect(detail(wrapper, 'Delay')).toBe('0 ms')
    expect(detail(wrapper, 'Duration')).toBe('0:04.000')
    expect(detail(wrapper, 'Frame count')).toBe('—')
    expect(detail(wrapper, 'Dispositions')).toBe('default')
    const flagged = { ...probedSource('multitrack').audio![0]!, frame_count: 172_500 }
    flagged.disposition = { ...flagged.disposition!, original: true }
    const more = mountTable('audio', [flagged])
    await more.find('.track-table__toggle').trigger('click')
    expect(detail(more, 'Dispositions')).toBe('default, original')
    expect(detail(more, 'Frame count')).toBe('172,500')
    expect(detail(wrapper, 'ENCODER')).toBe('Lavc63.1.102 ac3')
    expect(detail(wrapper, 'Roles')).toBe(
      'Main (Set by a disposition flag in the file) disposition default',
    )
    await toggle.trigger('click')
    expect(wrapper.find('.track-table__details').exists()).toBe(false)
  })

  it('expands from a click anywhere on the row', async () => {
    const wrapper = mountTable('audio', probedSource('multitrack').audio!)
    await wrapper.findAll('.track-table__row')[2]!.trigger('click')
    expect(wrapper.findAll('.track-table__toggle')[2]!.attributes('aria-expanded')).toBe('true')
    expect(wrapper.findAll('.track-table__details')).toHaveLength(1)
  })
})

describe('the subtitle source table', () => {
  it('shows the format, the type and the event count', () => {
    const pgs = probedSource('pgs').subtitles as SubtitleStream[]
    const counted = [{ ...pgs[0]!, event_count: 3655, event_count_source: 'stats_tag' }, pgs[1]]
    const wrapper = mountTable('subtitle', counted)
    expect(cells(wrapper, 0)).toEqual([
      '1',
      'eng',
      'English',
      'PGS',
      'bitmap',
      '3,655',
      'Main (Set by a disposition flag in the file) Default',
    ])
    expect(cells(wrapper, 1)[5]).toBe('—')
  })

  it('shows the canvas and the forced events in the details', async () => {
    const pgs = probedSource('pgs').subtitles as SubtitleStream[]
    const wrapper = mountTable('subtitle', [
      { ...pgs[1]!, event_count: 3655, forced_event_count: 1200 },
    ])
    await wrapper.find('.track-table__toggle').trigger('click')
    expect(detail(wrapper, 'Canvas')).toBe('720×480')
    expect(detail(wrapper, 'Events')).toMatch(/^3,655\b/)
    expect(detail(wrapper, 'Forced events')).toBe('1,200')
    expect(detail(wrapper, 'Delay')).toBe('+200 ms')
  })

  it('says when the source has no tracks of the kind', () => {
    const wrapper = mountTable('subtitle', [])
    expect(wrapper.text()).toBe('The source has no subtitle tracks.')
  })
})

function run(kind: ScanKind, streamIndex: number | null, progress: number | null): ScanRun {
  return { sourceId: 'src', kind, streamIndex, taskId: 'task', progress }
}

function endTask(state: TaskInfo['state']): void {
  useTasksStore().tasks = { task: { id: 'task', kind: 'scan', state } }
}

function measuredBitrate(stream: AudioStream): AudioStream {
  return { ...stream, bitrate: { value: 2_140_063, source: 'measured' } }
}

function estimated(samples: number | null): AudioStream {
  return {
    ...(probedSource('dts-hd-ma').audio![0] as AudioStream),
    bitrate: { value: 1_509_400, source: 'estimated', samples },
  }
}

const pgsStreams = () => probedSource('pgs').subtitles as SubtitleStream[]

const button = (wrapper: VueWrapper, name: string) =>
  wrapper.findAll('button').find((candidate) => candidate.attributes('aria-label') === name)

function mountScans(
  kind: 'audio' | 'subtitle',
  streams: unknown[],
  sourceId: string | null = 'src',
) {
  const wrapper = mountBase(TrackTable, { props: { kind, streams, sourceId } })
  mounted.push(wrapper)
  const scans = useScansStore()
  return {
    wrapper,
    scans,
    measureBitrate: vi.spyOn(scans, 'measureBitrate').mockResolvedValue(),
    scanSubtitles: vi.spyOn(scans, 'scanSubtitles').mockResolvedValue(),
    measureLoudness: vi.spyOn(scans, 'measureLoudness').mockResolvedValue(null),
    cancel: vi.spyOn(scans, 'cancel').mockResolvedValue(),
  }
}

describe('the scans in the source tables', () => {
  it('offers Measure for a track without a bitrate, and measures it without expanding the row', async () => {
    const { wrapper, measureBitrate } = mountScans('audio', probedSource('dts-hd-ma').audio!)
    expect(button(wrapper, 'Measure the bitrate of track 2')).toBeUndefined()
    const measure = button(wrapper, 'Measure the bitrate of track 1')!
    expect(measure.text()).toBe('Measure')
    await measure.trigger('click')
    expect(measureBitrate).toHaveBeenCalledExactlyOnceWith('src', 1)
    expect(wrapper.find('.track-table__details').exists()).toBe(false)
  })

  it('offers no scan without a source to scan', () => {
    const { wrapper } = mountScans('audio', probedSource('dts-hd-ma').audio!, null)
    expect(wrapper.findAll('[data-scan]')).toEqual([])
  })

  it('shows a running measurement’s progress and cancels it', async () => {
    const { wrapper, scans, cancel } = mountScans('audio', probedSource('dts-hd-ma').audio!)
    const measuring = run('bitrate', 1, 0.4)
    scans.runs = [measuring]
    await nextTick()
    expect(button(wrapper, 'Measure the bitrate of track 1')).toBeUndefined()
    const bar = wrapper.find('[role="progressbar"]')
    expect(bar.attributes('aria-label')).toBe('Measuring the bitrate of track 1')
    expect(bar.attributes('aria-valuenow')).toBe('40')
    await button(wrapper, 'Cancel the bitrate measurement of track 1')!.trigger('click')
    expect(cancel).toHaveBeenCalledExactlyOnceWith(measuring)
  })

  it('counts every subtitle track, or one track whose count is unknown', async () => {
    const pgs = probedSource('pgs').subtitles as SubtitleStream[]
    const { wrapper, scanSubtitles } = mountScans('subtitle', [
      { ...pgs[0]!, event_count: 12 },
      pgs[1],
    ])
    expect(button(wrapper, 'Count the events of track 1')).toBeUndefined()
    await button(wrapper, 'Count the events of track 2')!.trigger('click')
    expect(scanSubtitles).toHaveBeenLastCalledWith('src', [2])
    await button(wrapper, 'Count events of every subtitle track')!.trigger('click')
    expect(scanSubtitles).toHaveBeenLastCalledWith('src', undefined)
    expectNamesStartWithText(wrapper)
  })

  it('turns a track’s own count off while every track is counted', async () => {
    const pgs = probedSource('pgs').subtitles as SubtitleStream[]
    const { wrapper, scans } = mountScans('subtitle', pgs)
    scans.runs = [run('subtitle', null, null)]
    await nextTick()
    expect(button(wrapper, 'Count the events of track 1')!.attributes('disabled')).toBeDefined()
    expect(wrapper.find('[role="progressbar"]').attributes('aria-label')).toBe(
      'Counting the events of every subtitle track',
    )
  })

  it('counts a track again from its details once its count is known', async () => {
    const pgs = probedSource('pgs').subtitles as SubtitleStream[]
    const { wrapper, scanSubtitles } = mountScans('subtitle', [{ ...pgs[1]!, event_count: 4 }])
    await wrapper.find('.track-table__toggle').trigger('click')
    expect(detail(wrapper, 'Forced events')).toBe(
      'Unknown: count the events to find the forced ones',
    )
    await button(wrapper, 'Count the events of track 2')!.trigger('click')
    expect(scanSubtitles).toHaveBeenCalledExactlyOnceWith('src', [2])
  })

  it('shows the forced events beside the count', () => {
    const pgs = probedSource('pgs').subtitles as SubtitleStream[]
    const { wrapper } = mountScans('subtitle', [
      { ...pgs[0]!, event_count: 12, forced_event_count: 2, event_count_source: 'measured' },
    ])
    expect(cells(wrapper, 0)[5]).toBe('12 2 forced')
  })

  it('measures a track’s loudness from its details and shows the three values', async () => {
    const { wrapper, scans, measureLoudness } = mountScans(
      'audio',
      probedSource('dts-hd-ma').audio!,
    )
    await wrapper.find('.track-table__toggle').trigger('click')
    expect(detail(wrapper, 'Loudness')).toBe('Measure loudness')
    expectNamesStartWithText(wrapper)
    await button(wrapper, 'Measure loudness of track 1')!.trigger('click')
    expect(measureLoudness).toHaveBeenCalledExactlyOnceWith('src', 1)

    scans.loudness = {
      'src:1': { path: '/m.mkv', stream_index: 1, integrated: -22.47, true_peak: -20, lra: 2.2 },
      'other:1': { path: '/o.mkv', stream_index: 1, integrated: -1, true_peak: -1, lra: 1 },
    }
    await nextTick()
    expect(detail(wrapper, 'Integrated loudness')).toBe('−22.5 LUFS')
    expect(detail(wrapper, 'True peak')).toBe('−20.0 dBTP')
    expect(detail(wrapper, 'Loudness range')).toBe('2.2 LU')
    expect(button(wrapper, 'Measure again: loudness of track 1')!.text()).toBe('Measure again')
    expectNamesStartWithText(wrapper)
  })

  it('keeps the focus on the scan’s buttons as they replace each other', async () => {
    const { wrapper, scans } = mountScans('audio', probedSource('dts-hd-ma').audio!)
    button(wrapper, 'Measure the bitrate of track 1')!.element.focus()
    scans.runs = [run('bitrate', 1, null)]
    await flushPromises()
    const cancel = button(wrapper, 'Cancel the bitrate measurement of track 1')!
    expect(document.activeElement).toBe(cancel.element)
    scans.runs = []
    await flushPromises()
    expect(document.activeElement).toBe(button(wrapper, 'Measure the bitrate of track 1')!.element)
  })

  it('leaves the focus alone when a scan starts while it is elsewhere', async () => {
    const { wrapper, scans } = mountScans('audio', probedSource('dts-hd-ma').audio!)
    const toggle = wrapper.findAll<HTMLButtonElement>('.track-table__toggle')[1]!.element
    toggle.focus()
    scans.runs = [run('bitrate', 1, null)]
    await flushPromises()
    expect(document.activeElement).toBe(toggle)
  })

  it('gives the focus to the row when the measured value replaces the scan', async () => {
    const audio = probedSource('dts-hd-ma').audio!
    const { wrapper, scans } = mountScans('audio', audio)
    scans.runs = [run('bitrate', 1, null)]
    await flushPromises()
    button(wrapper, 'Cancel the bitrate measurement of track 1')!.element.focus()
    await wrapper.setProps({ streams: [measuredBitrate(audio[0]!), ...audio.slice(1)] })
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.findAll('.track-table__toggle')[0]!.element)
  })

  it('leaves the focus alone when a scan control goes away without it', async () => {
    const audio = probedSource('dts-hd-ma').audio!
    const { wrapper } = mountScans('audio', audio)
    const toggle = wrapper.findAll<HTMLButtonElement>('.track-table__toggle')[1]!.element
    toggle.focus()
    await wrapper.setProps({ streams: [measuredBitrate(audio[0]!), ...audio.slice(1)] })
    await flushPromises()
    expect(document.activeElement).toBe(toggle)
  })

  it('groups the digits of a bitrate', () => {
    const audio = probedSource('dts-hd-ma').audio!
    const { wrapper } = mountScans('audio', [measuredBitrate(audio[0]!)])
    expect(cells(wrapper, 0)[6]).toBe('2,140 kb/s measured')
  })

  describe('an estimated bitrate', () => {
    it('says it is an estimate, from how many samples, and offers Measure for the exact value', async () => {
      const { wrapper, measureBitrate } = mountScans('audio', [estimated(12)])
      expect(cells(wrapper, 0)[6]).toBe('≈ 1,509 kb/s Measure estimated from 12 samples')
      await button(wrapper, 'Measure the bitrate of track 1')!.trigger('click')
      expect(measureBitrate).toHaveBeenCalledExactlyOnceWith('src', 1)
      await wrapper.find('.track-table__toggle').trigger('click')
      expect(detail(wrapper, 'Bitrate')).toBe(
        "≈ 1,509 kb/s · Estimated from a sample of the file's clusters",
      )
    })

    it('counts one sample in the singular', () => {
      const { wrapper } = mountScans('audio', [estimated(1)])
      expect(cells(wrapper, 0)[6]).toBe('≈ 1,509 kb/s Measure estimated from one sample')
    })

    it('says only "estimated" when the probe gave no count', () => {
      const { wrapper } = mountScans('audio', [estimated(null)])
      expect(cells(wrapper, 0)[6]).toBe('≈ 1,509 kb/s Measure estimated')
    })

    it('offers no Measure once the bitrate is measured', () => {
      const { wrapper } = mountScans('audio', [measuredBitrate(estimated(12))])
      expect(wrapper.findAll('[data-scan="bitrate"]')).toEqual([])
    })
  })

  const loud = { path: '/m.mkv', stream_index: 1, integrated: -22.47, true_peak: -20, lra: 2.2 }

  it.each([
    {
      what: 'a measured bitrate',
      ended: run('bitrate', 1, null),
      streams: () => [measuredBitrate(probedSource('dts-hd-ma').audio![0]!)],
      said: 'Track 1: 2,140 kb/s, measured.',
    },
    {
      what: 'a bitrate scan that found none',
      ended: run('bitrate', 1, null),
      streams: () => probedSource('dts-hd-ma').audio!,
      said: 'Track 1: no bitrate could be measured.',
    },
    {
      what: 'a loudness',
      ended: run('loudness', 1, null),
      streams: () => probedSource('dts-hd-ma').audio!,
      said: 'Track 1: integrated loudness −22.5 LUFS, true peak −20.0 dBTP, loudness range 2.2 LU.',
    },
    {
      what: 'a track’s events with the forced ones',
      ended: run('subtitle', 2, null),
      streams: () => [{ ...pgsStreams()[1]!, event_count: 4, forced_event_count: 2 }],
      said: 'Track 2: 4 events counted, 2 forced.',
    },
    {
      what: 'one event with the forced ones',
      ended: run('subtitle', 2, null),
      streams: () => [{ ...pgsStreams()[1]!, event_count: 1, forced_event_count: 0 }],
      said: 'Track 2: one event counted, 0 forced.',
    },
    {
      what: 'thousands of events',
      ended: run('subtitle', 2, null),
      streams: () => [{ ...pgsStreams()[1]!, event_count: 3655, forced_event_count: 1200 }],
      said: 'Track 2: 3,655 events counted, 1,200 forced.',
    },
    {
      what: 'a track’s events',
      ended: run('subtitle', 2, null),
      streams: () => [{ ...pgsStreams()[1]!, event_count: 1 }],
      said: 'Track 2: one event counted.',
    },
    {
      what: 'a count that found nothing to show',
      ended: run('subtitle', 2, null),
      streams: () => [pgsStreams()[1]!],
      said: 'Counting the events of track 2: done.',
    },
    {
      what: 'every track’s events',
      ended: run('subtitle', null, null),
      streams: pgsStreams,
      said: 'The events of every subtitle track are counted.',
    },
  ])('announces what a finished scan found: $what', async ({ ended, streams, said }) => {
    const list = streams()
    const { wrapper, scans } = mountScans(ended.kind === 'subtitle' ? 'subtitle' : 'audio', list)
    scans.runs = [ended]
    await nextTick()
    endTask('done')
    if (ended.kind === 'loudness') scans.loudness = { 'src:1': loud }
    scans.runs = []
    await flushPromises()
    expect(wrapper.find('[data-role="scan-status"]').text()).toBe(said)
  })

  it('announces a cancelled scan, and leaves a failed one to its error toast', async () => {
    const { wrapper, scans } = mountScans('audio', probedSource('dts-hd-ma').audio!)
    const status = () => wrapper.find('[data-role="scan-status"]').text()
    scans.runs = [run('bitrate', 1, null)]
    await nextTick()
    endTask('cancelled')
    scans.runs = []
    await flushPromises()
    expect(status()).toBe('Measuring the bitrate of track 1: cancelled.')

    scans.runs = [{ ...run('loudness', 1, null), taskId: 'other' }]
    await nextTick()
    useTasksStore().tasks = { other: { id: 'other', kind: 'scan', state: 'failed' } }
    scans.runs = []
    await flushPromises()
    expect(status()).toBe('Measuring the bitrate of track 1: cancelled.')
  })

  it('shows a dash for a loudness FFmpeg gives as infinite', async () => {
    const { wrapper, scans } = mountScans('audio', probedSource('dts-hd-ma').audio!)
    scans.loudness = {
      'src:1': { path: '/m.mkv', stream_index: 1, integrated: null, true_peak: null, lra: 0 },
    }
    await wrapper.find('.track-table__toggle').trigger('click')
    expect(detail(wrapper, 'Integrated loudness')).toBe('—')
    expect(detail(wrapper, 'Loudness range')).toBe('0.0 LU')
  })
})
