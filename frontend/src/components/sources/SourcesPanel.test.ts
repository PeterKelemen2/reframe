import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { MediaSource, Schemas, SourceEntry } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { platform } from '@/platform'
import { useSourcesStore } from '@/stores/sources'

import SourcesPanel from './SourcesPanel.vue'

function media(path: string, warnings: string[] = []): MediaSource {
  return {
    schema_version: 1,
    ref: { path },
    container: { display_name: 'MKV', duration: 65 },
    video: [
      {
        index: 0,
        type_index: 0,
        kind: 'video',
        display_codec: 'H.264',
        width: 1920,
        height: 1080,
        vfr: false,
        field_order: 'progressive',
        rotation: 0,
        closed_captions: false,
      },
    ],
    warnings,
  }
}

function entry(path: string, warnings: string[] = []): SourceEntry {
  return { id: path.split('/').at(-1) ?? path, path, source: media(path, warnings) }
}

const episodes = ['E01', 'E02', 'E05'].map((name) => entry(`/m/show/Show.S01${name}.mkv`))
const movie = entry('/m/movie.mkv', ['The container reports no duration.'])

const grouping: Schemas['BatchGrouping'] = {
  groups: [
    {
      id: 'g1',
      name: 'Show S01',
      level: 'standard',
      representative: episodes[0]?.path ?? '',
      fingerprint: {} as Schemas['Fingerprint'],
      members: episodes.map((episode, index) => ({
        path: episode.path,
        season: 1,
        episode: [1, 2, 5][index],
        match: index === 2 ? 'near' : 'exact',
        differences: index === 2 ? ['1 extra track (eng AC-3 2.0 "Commentary")'] : [],
      })),
    },
  ],
  issues: [],
}

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

async function mountPanel(state: (sources: ReturnType<typeof useSourcesStore>) => void = () => {}) {
  let store: ReturnType<typeof useSourcesStore> | undefined
  const result = await mountShell(SourcesPanel, {
    setup: () => {
      store = useSourcesStore()
      state(store)
    },
  })
  mounted.push(result.wrapper)
  if (store === undefined) throw new Error('no store')
  const sources = store
  return {
    wrapper: result.wrapper,
    sources,
    select: vi.spyOn(sources, 'select').mockResolvedValue(),
    removeMany: vi.spyOn(sources, 'removeMany').mockResolvedValue(),
  }
}

const $ = (selector: string) => document.querySelector<HTMLElement>(selector)
const $$ = (selector: string) => [...document.querySelectorAll<HTMLElement>(selector)]
const item = (id: string) => $(`[data-key="source:${id}"]`) as HTMLElement
const groupItem = () => $('[data-key="group:g1"]') as HTMLElement
const text = (element: Element | null) => element?.textContent?.replace(/\s+/g, ' ').trim()

/** Text as a screen reader computes it: `aria-label` replaces content, hidden parts drop out. */
function spoken(node: Node): string {
  if (node instanceof Element) {
    if (node.getAttribute('aria-hidden') === 'true') return ''
    const label = node.getAttribute('aria-label')
    if (label !== null) return label
    return [...node.childNodes].map(spoken).join(' ')
  }
  return node.nodeType === Node.TEXT_NODE ? (node.textContent ?? '') : ''
}

function referenced(element: HTMLElement, attribute: string): string | undefined {
  const ids = element.getAttribute(attribute)
  if (ids === null) return undefined
  return ids
    .split(/\s+/)
    .map((id) => {
      const target = document.getElementById(id)
      return target === null ? '' : spoken(target)
    })
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim()
}

async function key(name: string): Promise<void> {
  const target = document.activeElement ?? document.body
  target.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true }))
  await flushPromises()
}

function withShow(sources: ReturnType<typeof useSourcesStore>): void {
  sources.entries = [movie, ...episodes]
  sources.grouping = grouping
  sources.activeId = 'movie.mkv'
}

describe('the sources panel', () => {
  it('shows each source with its short line and its warnings, the active one marked', async () => {
    await mountPanel(withShow)
    expect(text(item('movie.mkv').querySelector('[data-field="summary"]'))).toBe(
      'MKV · 1:05 · H.264 1920×1080',
    )
    expect($$('[data-field="warning"]').map(text)).toEqual([
      'Probe warning: The container reports no duration.',
    ])
    expect(item('movie.mkv').getAttribute('aria-selected')).toBe('true')
    expect(item('Show.S01E01.mkv').getAttribute('aria-selected')).toBe('false')
  })

  it('names a source by its file and describes it by its line and warnings, without its buttons', async () => {
    await mountPanel(withShow)
    expect(referenced(item('movie.mkv'), 'aria-labelledby')).toBe('movie.mkv')
    expect(referenced(item('movie.mkv'), 'aria-describedby')).toBe(
      'MKV · 1:05 · H.264 1920×1080 Probe warning: The container reports no duration.',
    )
    expect(referenced(item('Show.S01E05.mkv'), 'aria-labelledby')).toBe(
      'Near match: added with differences E05 Show.S01E05.mkv',
    )
    expect(referenced(item('Show.S01E05.mkv'), 'aria-describedby')).toBe(
      '1 extra track (eng AC-3 2.0 "Commentary")',
    )
  })

  it('shows a group with its size, level and near matches, its members by episode', async () => {
    await mountPanel(withShow)
    expect(text($('.sources-panel__group-name'))).toBe('Show S01')
    expect($$('.sources-panel__group-meta').map((meta) => [...meta.children].map(text))).toEqual([
      ['3 files', 'standard match'],
      ['1 near match'],
    ])
    expect($$('.sources-panel__member .source-item__label').map(text)).toEqual([
      'E01',
      'E02',
      'E05',
    ])
    expect($$('.sources-panel__member').map((row) => row.dataset.match)).toEqual([
      'exact',
      'exact',
      'near',
    ])
    expect($$('[data-field="difference"]').map(text)).toEqual([
      '1 extra track (eng AC-3 2.0 "Commentary")',
    ])
  })

  it('collapses and expands a group with a click and with the arrow keys', async () => {
    await mountPanel(withShow)
    $('.sources-panel__group-head')?.click()
    await flushPromises()
    expect(groupItem().getAttribute('aria-expanded')).toBe('false')
    expect($$('.sources-panel__member')).toEqual([])
    groupItem().focus()
    await key('ArrowRight')
    expect(groupItem().getAttribute('aria-expanded')).toBe('true')
    await key('ArrowRight')
    expect(document.activeElement).toBe(item('Show.S01E01.mkv'))
    await key('ArrowLeft')
    expect(document.activeElement).toBe(groupItem())
    await key('ArrowLeft')
    expect(groupItem().getAttribute('aria-expanded')).toBe('false')
    await key('Enter')
    expect(groupItem().getAttribute('aria-expanded')).toBe('true')
  })

  it('chooses a source with a click', async () => {
    const { select } = await mountPanel(withShow)
    item('Show.S01E05.mkv').click()
    await flushPromises()
    expect(select).toHaveBeenCalledExactlyOnceWith('Show.S01E05.mkv')
  })

  it('moves with the arrow keys, Home and End, and chooses with Enter', async () => {
    const { select } = await mountPanel(withShow)
    expect(item('movie.mkv').tabIndex).toBe(0)
    expect(groupItem().tabIndex).toBe(-1)
    item('movie.mkv').focus()
    await key('ArrowDown')
    expect(document.activeElement).toBe(groupItem())
    await key('ArrowDown')
    await key('ArrowDown')
    expect(document.activeElement).toBe(item('Show.S01E02.mkv'))
    expect(item('Show.S01E02.mkv').tabIndex).toBe(0)
    await key('Enter')
    expect(select).toHaveBeenCalledExactlyOnceWith('Show.S01E02.mkv')
    await key('End')
    expect(document.activeElement).toBe(item('Show.S01E05.mkv'))
    await key('Home')
    expect(document.activeElement).toBe(item('movie.mkv'))
    await key('ArrowUp')
    expect(document.activeElement).toBe(item('movie.mkv'))
  })

  it('asks before Delete removes a source, then moves the focus to the next one', async () => {
    const { sources, removeMany } = await mountPanel(withShow)
    removeMany.mockImplementation(async (ids) => {
      sources.entries = sources.entries.filter((found) => !ids.includes(found.id))
    })
    item('Show.S01E01.mkv').focus()
    await key('Delete')
    expect(text($('[data-state="confirm-remove"] p'))).toBe(
      'Remove Show.S01E01.mkv from the sources?',
    )
    expect(removeMany).not.toHaveBeenCalled()
    expect(document.activeElement).toBe($('[data-action="confirm-remove"]'))
    $('[data-action="confirm-remove"]')?.click()
    await flushPromises()
    expect(removeMany).toHaveBeenCalledExactlyOnceWith(['Show.S01E01.mkv'])
    expect($('[data-state="confirm-remove"]')).toBeNull()
    expect(document.activeElement).toBe(item('Show.S01E02.mkv'))
  })

  it('keeps the source on Escape and gives the focus back', async () => {
    const { removeMany } = await mountPanel(withShow)
    item('movie.mkv').focus()
    await key('Delete')
    await key('Escape')
    expect($('[data-state="confirm-remove"]')).toBeNull()
    expect(removeMany).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(item('movie.mkv'))
  })

  it('asks to remove every source of a group from its row', async () => {
    const { removeMany } = await mountPanel(withShow)
    groupItem().focus()
    await key('Delete')
    expect(text($('[data-state="confirm-remove"] p'))).toBe('Remove these 3 sources?')
    $('[data-action="confirm-remove"]')?.click()
    await flushPromises()
    expect(removeMany).toHaveBeenCalledExactlyOnceWith(episodes.map((episode) => episode.id))
  })

  it('removes through the row’s button after the same question', async () => {
    const { removeMany } = await mountPanel(withShow)
    item('movie.mkv').querySelector<HTMLElement>('[data-action="remove"]')?.click()
    await flushPromises()
    expect(text($('[data-state="confirm-remove"] p'))).toBe('Remove movie.mkv from the sources?')
    $('[data-action="confirm-remove"]')?.click()
    await flushPromises()
    expect(removeMany).toHaveBeenCalledExactlyOnceWith(['movie.mkv'])
  })

  it('shows each probe run with its progress; the count once the task gives one', async () => {
    await mountPanel((sources) => {
      sources.probing = [
        { taskId: 't1', paths: ['/m/show'], progress: null, message: 'Probing show' },
        { taskId: 't2', paths: ['/m/a.mkv', '/m/b.mkv'], progress: 0.25, message: '1/4 files' },
      ]
    })
    const runs = $$('[data-state="probing"]')
    expect(runs.map((run) => text(run.querySelector('.sources-panel__run-label')))).toEqual([
      'Reading show…',
      'Reading 2 items…',
    ])
    expect(runs[0]?.querySelector('.sources-panel__run-message')).toBeNull()
    expect(text(runs[1]?.querySelector('.sources-panel__run-message') ?? null)).toBe('1/4 files')
    expect(runs[1]?.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe('25')
    expect($('[data-state="no-sources"]')).toBeNull()
  })

  it('says how to start when nothing is open', async () => {
    await mountPanel()
    expect(text($('[data-state="no-sources"]'))).toContain('No sources open')
  })

  it('opens files, a folder, or a folder with its subfolders', async () => {
    const { sources } = await mountPanel()
    const pick = vi.spyOn(sources, 'pick').mockResolvedValue()
    const pickFolder = vi.spyOn(sources, 'pickFolder').mockResolvedValue()
    $('[data-action="open-files"]')?.click()
    $('[data-action="open-folder"]')?.click()
    $('[data-action="open-folder-recursive"]')?.click()
    await flushPromises()
    expect(pick).toHaveBeenCalledOnce()
    expect(pickFolder.mock.calls).toEqual([[{ recursive: false }], [{ recursive: true }]])
  })

  it('opens the paths of files dropped on the desktop window, until the panel goes', async () => {
    let dropped: ((paths: string[]) => void) | null = null
    const stop = vi.fn<() => void>()
    vi.spyOn(platform, 'onFilesDropped').mockImplementation((callback) => {
      dropped = callback
      return stop
    })
    const { wrapper, sources } = await mountPanel()
    const open = vi.spyOn(sources, 'open').mockResolvedValue([])
    ;(dropped as ((paths: string[]) => void) | null)?.(['/m/a.mkv'])
    expect(open).toHaveBeenCalledExactlyOnceWith(['/m/a.mkv'])
    wrapper.unmount()
    mounted.splice(0)
    expect(stop).toHaveBeenCalledOnce()
  })

  it('offers to read a source again whose file changed or is gone', async () => {
    const { sources } = await mountPanel((store) => {
      store.entries = [{ id: 'gone.mkv', path: '/m/gone.mkv', source: null }]
    })
    const open = vi.spyOn(sources, 'open').mockResolvedValue([])
    expect(text($('[data-state="stale"] span'))).toBe(
      'The file changed or is gone since it was read.',
    )
    $('[data-action="reprobe"]')?.click()
    await flushPromises()
    expect(open).toHaveBeenCalledExactlyOnceWith(['/m/gone.mkv'], { select: false })
  })
})
