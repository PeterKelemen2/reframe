import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed } from 'vue'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { JobSettings, MediaSource, Schemas, SourceEntry } from '@/api/types'
import { clipboard } from '@/components/batch/clipboard'
import { mountShell } from '@/components/shell/testing'
import { sampleJob, samplePreset } from '@/editor/testing/samples'
import { platform } from '@/platform'
import { type EditorTarget, useEditorStore } from '@/stores/editor'
import { templateOfPreset } from '@/stores/presets'
import { useSourcesStore } from '@/stores/sources'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

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

const queue = vi.hoisted(() => ({ queueGroup: vi.fn<(id: string) => Promise<void>>() }))
vi.mock('@/composables/useQueueGroup', () => ({
  useQueueGroup: () => ({ busy: computed(() => false), queueGroup: queue.queueGroup }),
}))

const mounted: { unmount(): void }[] = []
let server: FakeServer

beforeEach(() => {
  server = new FakeServer()
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  queue.queueGroup.mockReset().mockResolvedValue()
  clipboard.value = null
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.restoreAllMocks()
})

async function mountPanel(
  state: (
    sources: ReturnType<typeof useSourcesStore>,
    editor: ReturnType<typeof useEditorStore>,
  ) => void = () => {},
) {
  let store: ReturnType<typeof useSourcesStore> | undefined
  let editorStore: ReturnType<typeof useEditorStore> | undefined
  const result = await mountShell(SourcesPanel, {
    setup: () => {
      store = useSourcesStore()
      editorStore = useEditorStore()
      state(store, editorStore)
    },
  })
  mounted.push(result.wrapper)
  if (store === undefined || editorStore === undefined) throw new Error('no store')
  const sources = store
  const editor = editorStore
  return {
    wrapper: result.wrapper,
    sources,
    editor,
    select: vi.spyOn(sources, 'select').mockResolvedValue(),
    removeMany: vi.spyOn(sources, 'removeMany').mockResolvedValue(),
    showFile: vi.spyOn(editor, 'showFile').mockResolvedValue(),
    editGroup: vi.spyOn(editor, 'editGroup').mockResolvedValue(),
    mergeIntoGroup: vi.spyOn(editor, 'mergeIntoGroup').mockResolvedValue(),
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

  it('names a group by its name and its lines, without its buttons or members', async () => {
    await mountPanel(editing)
    expect(referenced(groupItem(), 'aria-labelledby')).toBe(
      'Show S01 Editing 3 files standard match 1 near match',
    )
    expect($('.sources-panel__group-name')?.title).toBe('Show S01')
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

const TEMPLATE = templateOfPreset(samplePreset())

function editing(
  sources: ReturnType<typeof useSourcesStore>,
  editor: ReturnType<typeof useEditorStore>,
): void {
  withShow(sources)
  sources.activeId = 'Show.S01E01.mkv'
  editor.target = {
    kind: 'group',
    groupId: 'g1',
    sourceId: 'Show.S01E01.mkv',
    job: sampleJob(),
    template: TEMPLATE,
    presetId: null,
    overrides: {},
    scope: 'group',
  }
}

function jobOf(id: string): JobSettings {
  const job = sampleJob()
  job.source = { path: `/m/${id}`, fingerprint: null }
  return job
}

function openJob(id: string) {
  return (
    sources: ReturnType<typeof useSourcesStore>,
    editor: ReturnType<typeof useEditorStore>,
  ) => {
    withShow(sources)
    sources.activeId = id
    editor.target = { kind: 'job', sourceId: id, job: jobOf(id) }
  }
}

const menuItems = () => $$('.p-contextmenu [role="menuitem"]')
const menuItem = (label: string) =>
  menuItems().find((found) => found.getAttribute('aria-label') === label) as HTMLElement

async function menuKey(name: string, code: string): Promise<void> {
  const list = $('.p-contextmenu [role="menubar"]') as HTMLElement
  list.focus()
  list.dispatchEvent(new KeyboardEvent('keydown', { key: name, code, bubbles: true }))
  await flushPromises()
}

async function rightClick(element: HTMLElement): Promise<void> {
  element.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))
  await flushPromises()
}

async function choose(label: string): Promise<void> {
  menuItem(label).querySelector<HTMLElement>('.p-contextmenu-item-content')?.click()
  await flushPromises()
}

describe('a batch group in the sources panel', () => {
  it('marks the edited group, and shows its members in the group rather than as jobs', async () => {
    const { select, showFile } = await mountPanel(editing)
    expect(groupItem().getAttribute('aria-current')).toBe('true')
    expect(text(groupItem().querySelector('[data-field="editing"]'))).toBe('Editing')
    item('Show.S01E05.mkv').click()
    await flushPromises()
    item('Show.S01E02.mkv').focus()
    await key('Enter')
    expect(showFile.mock.calls).toEqual([['Show.S01E05.mkv'], ['Show.S01E02.mkv']])
    item('movie.mkv').click()
    await flushPromises()
    expect(select).toHaveBeenCalledExactlyOnceWith('movie.mkv')
  })

  it('opens a member as one job while no group is edited', async () => {
    const { select, showFile } = await mountPanel(openJob('movie.mkv'))
    expect(groupItem().getAttribute('aria-current')).toBeNull()
    item('Show.S01E02.mkv').click()
    await flushPromises()
    expect(select).toHaveBeenCalledExactlyOnceWith('Show.S01E02.mkv')
    expect(showFile).not.toHaveBeenCalled()
  })

  it('edits, checks and queues a group from its row', async () => {
    const { editGroup } = await mountPanel(withShow)
    const openMatrix = vi.spyOn(useUiStore(), 'openMatrix')
    groupItem().querySelector<HTMLElement>('[data-action="edit-group"]')?.click()
    await flushPromises()
    expect(editGroup).toHaveBeenCalledExactlyOnceWith('g1')
    groupItem().querySelector<HTMLElement>('[data-action="check-group"]')?.click()
    await flushPromises()
    expect(editGroup).toHaveBeenCalledTimes(2)
    expect(openMatrix).toHaveBeenCalledOnce()
    groupItem().querySelector<HTMLElement>('[data-action="queue-group"]')?.click()
    await flushPromises()
    expect(queue.queueGroup).toHaveBeenCalledExactlyOnceWith('g1')
    expect(groupItem().getAttribute('aria-expanded')).toBe('true')
  })

  it('checks the edited group without editing it again', async () => {
    const { editGroup } = await mountPanel(editing)
    const openMatrix = vi.spyOn(useUiStore(), 'openMatrix')
    expect(groupItem().querySelector('[data-action="edit-group"]')).toBeNull()
    groupItem().querySelector<HTMLElement>('[data-action="check-group"]')?.click()
    await flushPromises()
    expect(editGroup).not.toHaveBeenCalled()
    expect(openMatrix).toHaveBeenCalledOnce()
  })

  it('opens the context menu with Shift+F10 and the context menu key, and its actions work', async () => {
    const { editGroup } = await mountPanel(withShow)
    groupItem().focus()
    groupItem().dispatchEvent(
      new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true }),
    )
    await flushPromises()
    expect(
      menuItems()
        .slice(0, 3)
        .map((found) => found.getAttribute('aria-label')),
    ).toEqual(['Edit group', 'Check group', 'Add group to queue'])
    await menuKey('ArrowDown', 'ArrowDown')
    await menuKey('Enter', 'Enter')
    expect(editGroup).toHaveBeenCalledExactlyOnceWith('g1')

    item('movie.mkv').focus()
    await key('ContextMenu')
    expect(menuItem('Copy audio settings')).toBeDefined()
    await menuKey('Escape', 'Escape')
    await new Promise((resolve) => setTimeout(resolve))
    expect(document.activeElement).toBe(item('movie.mkv'))
  })

  it('copies a section of the open job from its row only', async () => {
    await mountPanel(openJob('Show.S01E01.mkv'))
    await rightClick(item('Show.S01E02.mkv'))
    expect(menuItem('Copy audio settings').getAttribute('aria-disabled')).toBe('true')
    await rightClick(item('Show.S01E01.mkv'))
    expect(menuItems().map((found) => found.getAttribute('aria-label'))).toEqual([
      'Copy dimensions settings',
      'Copy filters settings',
      'Copy video settings',
      'Copy audio settings',
      'Copy subtitles settings',
      'Copy chapter options',
      'Copy tags',
      'Copy output naming settings',
      'Apply to group…',
    ])
    await choose('Copy audio settings')
    expect(clipboard.value).toEqual({
      from: 'job',
      section: 'audio',
      job: jobOf('Show.S01E01.mkv'),
      sourceId: 'Show.S01E01.mkv',
    })
  })

  it('copies a section of the edited group’s template from the group’s row only', async () => {
    await mountPanel(editing)
    await rightClick(item('Show.S01E01.mkv'))
    expect(menuItem('Copy audio settings').getAttribute('aria-disabled')).toBe('true')
    await rightClick(groupItem())
    await choose('Copy subtitles settings')
    expect(clipboard.value).toEqual({
      from: 'group',
      section: 'subtitles',
      template: TEMPLATE,
      groupId: 'g1',
    })
  })

  it('pastes a job’s section into a group', async () => {
    const { mergeIntoGroup } = await mountPanel(openJob('movie.mkv'))
    await rightClick(groupItem())
    expect(menuItems().some((found) => found.getAttribute('aria-label')?.startsWith('Paste'))).toBe(
      false,
    )
    const job = jobOf('Show.S01E05.mkv')
    clipboard.value = { from: 'job', section: 'audio', job, sourceId: 'Show.S01E05.mkv' }
    await rightClick(groupItem())
    await choose('Paste audio settings')
    expect(mergeIntoGroup).toHaveBeenCalledExactlyOnceWith('g1', job, 'Show.S01E05.mkv', ['audio'])
    expect(useToastStore().items.map((toast) => toast.summary)).toEqual([
      'Audio pasted into Show S01',
    ])
  })

  it('pastes a section into another file: opened first, then one undo step', async () => {
    const { editor, select } = await mountPanel(openJob('movie.mkv'))
    const before = jobOf('Show.S01E02.mkv')
    select.mockImplementation(async (id) => {
      editor.target = { kind: 'job', sourceId: id, job: before } as EditorTarget
    })
    const resolved = jobOf('Show.S01E02.mkv')
    resolved.audio = [{ ...resolved.audio![0]!, encoder: 'libopus', bitrate: 448 }]
    server
      .on('POST /api/batch/derive', TEMPLATE)
      .on('POST /api/batch/resolve', { rows: [{ path: '/m/x', job: resolved, status: 'ok' }] })
    clipboard.value = {
      from: 'job',
      section: 'audio',
      job: jobOf('movie.mkv'),
      sourceId: 'movie.mkv',
    }
    await rightClick(item('Show.S01E02.mkv'))
    await choose('Paste audio settings')
    expect(select).toHaveBeenCalledExactlyOnceWith('Show.S01E02.mkv')
    expect(editor.job?.audio).toEqual(resolved.audio)
    expect(editor.job?.subtitles).toEqual(before.subtitles)
    editor.undo()
    expect(editor.job?.audio).toEqual(before.audio)
    expect(editor.canUndo).toBe(false)
  })

  it('offers Apply to group only on the open job’s row of a group member', async () => {
    await mountPanel(openJob('movie.mkv'))
    await rightClick(item('movie.mkv'))
    expect(menuItem('Apply to group…')).toBeUndefined()
    await rightClick(item('Show.S01E02.mkv'))
    expect(menuItem('Apply to group…')).toBeUndefined()

    mounted.splice(0).forEach((wrapper) => wrapper.unmount())
    await mountPanel(openJob('Show.S01E02.mkv'))
    await rightClick(item('Show.S01E02.mkv'))
    await choose('Apply to group…')
    expect(text($('[data-dialog="apply-to-group"] .p-dialog-title'))).toBe(
      'Apply to group “Show S01”',
    )
  })
})
