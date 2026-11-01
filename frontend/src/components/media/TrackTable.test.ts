import type { VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import type { SubtitleStream } from '@/api/types'
import { mountBase } from '@/components/base/testing'
import { probedSource } from '@/components/tracks/testing'
import { type ScanKind, type ScanRun, useScansStore } from '@/stores/scans'

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

/** The text nodes of an element, one word group each, joined with spaces. */
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

/** The value of one detail of the expanded row. */
function detail(wrapper: VueWrapper, label: string): string | undefined {
  const pair = wrapper
    .findAll('.track-table__details .rf-kv')
    .find((candidate) => candidate.find('dt').text() === label)
  return pair && words(pair.find('dd').element)
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
      '3655',
      'Main (Set by a disposition flag in the file) Default',
    ])
    expect(cells(wrapper, 1)[5]).toBe('—')
  })

  it('shows the canvas and the forced events in the details', async () => {
    const pgs = probedSource('pgs').subtitles as SubtitleStream[]
    const wrapper = mountTable('subtitle', [{ ...pgs[1]!, forced_event_count: 12 }])
    await wrapper.find('.track-table__toggle').trigger('click')
    expect(detail(wrapper, 'Canvas')).toBe('720×480')
    expect(detail(wrapper, 'Forced events')).toBe('12')
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
    await button(wrapper, 'Count the events of every subtitle track')!.trigger('click')
    expect(scanSubtitles).toHaveBeenLastCalledWith('src', undefined)
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
    await button(wrapper, 'Measure the loudness of track 1')!.trigger('click')
    expect(measureLoudness).toHaveBeenCalledExactlyOnceWith('src', 1)

    scans.loudness = {
      'src:1': { path: '/m.mkv', stream_index: 1, integrated: -22.47, true_peak: -20, lra: 2.2 },
      'other:1': { path: '/o.mkv', stream_index: 1, integrated: -1, true_peak: -1, lra: 1 },
    }
    await nextTick()
    expect(detail(wrapper, 'Integrated loudness')).toBe('−22.5 LUFS')
    expect(detail(wrapper, 'True peak')).toBe('−20.0 dBTP')
    expect(detail(wrapper, 'Loudness range')).toBe('2.2 LU')
    expect(button(wrapper, 'Measure the loudness of track 1')!.text()).toBe('Measure again')
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
