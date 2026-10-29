import type { VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import type { SubtitleStream } from '@/api/types'
import { mountBase } from '@/components/base/testing'
import { probedSource } from '@/components/tracks/testing'

import TrackTable from './TrackTable.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
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
