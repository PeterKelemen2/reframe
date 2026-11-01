import { describe, expect, it } from 'vitest'

import type { MediaSource, Schemas, SourceEntry } from '@/api/types'

import { episodeLabels, panelItems, sourceSummary } from './panel'

type Member = Schemas['GroupMember']

function entry(path: string): SourceEntry {
  return { id: `id-${path}`, path, source: { schema_version: 1, ref: { path } } }
}

function group(name: string, paths: string[]): Schemas['BatchGroup'] {
  return {
    id: name,
    name,
    level: 'standard',
    representative: paths[0] ?? '',
    fingerprint: {} as Schemas['Fingerprint'],
    members: paths.map((path) => ({ path, match: 'exact' })),
  }
}

function shape(items: ReturnType<typeof panelItems>): string[] {
  return items.map((item) =>
    item.kind === 'source'
      ? item.entry.path
      : `${item.group.name}: ${item.rows.map((row) => row.entry.path).join(', ')}`,
  )
}

describe('panelItems', () => {
  const entries = ['/m/movie.mkv', '/m/s/E01.mkv', '/m/other.mkv', '/m/s/E02.mkv'].map(entry)

  it('lists the sources one by one without a grouping', () => {
    expect(shape(panelItems(entries, null))).toEqual([
      '/m/movie.mkv',
      '/m/s/E01.mkv',
      '/m/other.mkv',
      '/m/s/E02.mkv',
    ])
  })

  it('puts a group where its first open member was, in the group’s order', () => {
    const grouping = {
      groups: [
        group('Show', ['/m/s/E02.mkv', '/m/s/E01.mkv']),
        group('movie', ['/m/movie.mkv']),
        group('other', ['/m/other.mkv']),
      ],
    }
    expect(shape(panelItems(entries, grouping))).toEqual([
      '/m/movie.mkv',
      'Show: /m/s/E02.mkv, /m/s/E01.mkv',
      '/m/other.mkv',
    ])
  })

  it('shows a group with only one open member as that source alone', () => {
    const grouping = { groups: [group('Show', ['/m/s/E01.mkv', '/m/closed.mkv'])] }
    expect(shape(panelItems(entries, grouping))).toEqual([
      '/m/movie.mkv',
      '/m/s/E01.mkv',
      '/m/other.mkv',
      '/m/s/E02.mkv',
    ])
  })
})

function member(path: string, season: number | null, episode: number | null): Member {
  return { path, match: 'exact', season, episode }
}

describe('episodeLabels', () => {
  it('labels episodes of one season E05, and S01E05 when the group spans seasons', () => {
    expect(episodeLabels([member('/a', 1, 5), member('/b', 1, 6)])).toEqual(['E05', 'E06'])
    expect(episodeLabels([member('/a', 1, 5), member('/b', 2, 1)])).toEqual(['S01E05', 'S02E01'])
  })

  it('names a file without an episode, and two files of one episode, by the file name', () => {
    expect(
      episodeLabels([
        member('/x/Show.E01.A.mkv', 1, 1),
        member('/x/Show.E01.B.mkv', 1, 1),
        member('/x/Extra.mkv', null, null),
        member('/x/E02.mkv', 1, 2),
      ]),
    ).toEqual(['Show.E01.A.mkv', 'Show.E01.B.mkv', 'Extra.mkv', 'E02'])
  })
})

describe('sourceSummary', () => {
  it('names the container, the duration and the video', () => {
    const media: MediaSource = {
      schema_version: 1,
      ref: { path: '/m/a.mkv' },
      container: { display_name: 'MKV', duration: 3725 },
      video: [
        {
          index: 0,
          type_index: 0,
          kind: 'video',
          display_codec: 'HEVC Main 10',
          width: 3840,
          height: 2160,
          vfr: false,
          field_order: 'progressive',
          rotation: 0,
          closed_captions: false,
        },
      ],
    }
    expect(sourceSummary({ id: 'a', path: '/m/a.mkv', source: media })).toEqual([
      'MKV',
      '1:02:05',
      'HEVC Main 10 3840×2160',
    ])
  })

  it('is empty for a source whose file changed or is gone', () => {
    expect(sourceSummary({ id: 'a', path: '/m/a.mkv', source: null })).toEqual([])
  })
})
