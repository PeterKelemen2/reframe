import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { configureClient } from '@/api/client'
import { FakeServer, problem } from '@/api/testing/fakes'
import type { FsListing } from '@/api/types'
import { mountShell } from '@/components/shell/testing'

import { browse, currentRequest, finish } from './fileBrowser'
import FileBrowserDialog from './FileBrowserDialog.vue'

type Entry = FsListing['entries'][number]

// jsdom lays nothing out.
Element.prototype.scrollIntoView ??= function scrollIntoView() {}

const folder = (path: string): Entry => ({
  name: path.split('/').at(-1) ?? path,
  path,
  kind: 'folder',
})
const file = (path: string, size = 1_500_000): Entry => ({
  name: path.split('/').at(-1) ?? path,
  path,
  kind: 'file',
  size,
})

/** The server's folders below its roots; anything else is refused as outside the roots. */
const tree: Record<string, { parent: string | null; entries: Entry[] }> = {
  '/srv/media': {
    parent: null,
    entries: [
      folder('/srv/media/extras'),
      folder('/srv/media/season'),
      file('/srv/media/a.mkv'),
      file('/srv/media/b.mp4'),
      file('/srv/media/c.mkv'),
      file('/srv/media/d.mkv'),
    ],
  },
  '/srv/media/season': {
    parent: '/srv/media',
    entries: [file('/srv/media/season/E01.mkv'), file('/srv/media/season/E02.mkv')],
  },
  '/srv/media/extras': { parent: '/srv/media', entries: [] },
  '/srv/out': { parent: null, entries: [folder('/srv/out/done'), file('/srv/out/old.mkv')] },
  '/srv/out/done': { parent: '/srv/out', entries: [] },
}

let server: FakeServer
const mounted: { unmount(): void }[] = []

beforeEach(() => {
  server = new FakeServer()
    .on('GET /api/fs/roots', {
      roots: [
        { name: 'media', path: '/srv/media', kind: 'media' },
        { name: 'out', path: '/srv/out', kind: 'output' },
      ],
    })
    .on('GET /api/fs/list', (request) => {
      const path = new URLSearchParams(request.search).get('path') ?? ''
      const found = tree[path]
      if (found === undefined) {
        return problem(
          403,
          'path.outside_roots',
          'The path is outside the allowed folders',
          `${path} is not inside a folder that this server may read.`,
        )
      }
      return { path, ...found }
    })
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  // Leaves no request open for the next test.
  const left = currentRequest()
  if (left !== null) finish(left, null)
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountDialog() {
  const opener = document.createElement('button')
  document.body.append(opener)
  opener.focus()
  const { wrapper } = await mountShell(FileBrowserDialog)
  mounted.push(wrapper)
  return { opener }
}

const $ = <T extends Element = HTMLElement>(selector: string) => document.querySelector<T>(selector)
const $$ = (selector: string) => [...document.querySelectorAll<HTMLElement>(selector)]
const names = () => $$('.file-browser__entry').map((entry) => entry.dataset.name)
const selected = () =>
  $$('.file-browser__entry[aria-selected="true"]').map((entry) => entry.dataset.name)
const crumbs = () => $$('[data-role="crumb"]').map((crumb) => crumb.textContent?.trim())
const list = () => $('[role="listbox"]') as HTMLElement
const entry = (name: string) => $(`.file-browser__entry[data-name="${name}"]`) as HTMLElement

async function settled(): Promise<void> {
  await flushPromises()
  await flushPromises()
}

function click(element: Element | null, init: MouseEventInit = {}): Promise<void> {
  element?.dispatchEvent(new MouseEvent('click', { bubbles: true, ...init }))
  return settled()
}

function key(name: string, init: KeyboardEventInit = {}): Promise<void> {
  list().dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true, ...init }))
  return settled()
}

/** Opens the dialog and lets it list its first folder; `chosen` is what the picker gives. */
async function open(options: Parameters<typeof browse>[0]) {
  const chosen = browse(options)
  await settled()
  await settled()
  return { chosen }
}

describe('the file browser dialog', () => {
  it('shows the roots and the first media root’s folders and files in a modal dialog', async () => {
    await mountDialog()
    await open({ mode: 'files', multiple: true })
    await settled()
    expect($('[role="dialog"]')?.getAttribute('aria-modal')).toBe('true')
    expect($$('[data-role="root"]').map((root) => root.textContent?.trim())).toEqual([
      'mediaMedia folder',
      'outOutput folder',
    ])
    expect(crumbs()).toEqual(['media'])
    expect(names()).toEqual(['extras', 'season', 'a.mkv', 'b.mp4', 'c.mkv', 'd.mkv'])
    expect(entry('a.mkv').textContent).toContain('1.5 MB')
    expect(document.activeElement).toBe(list())
  })

  it('goes into a folder on a click, and back with the breadcrumbs and Up', async () => {
    await mountDialog()
    await open({ mode: 'files', multiple: true })
    await click(entry('season'))
    expect(crumbs()).toEqual(['media', 'season'])
    expect(names()).toEqual(['E01.mkv', 'E02.mkv'])
    await click($$('[data-role="crumb"]')[0] ?? null)
    expect(names()).toContain('season')
    await click(entry('season'))
    await click($('[data-action="up"]'))
    expect(crumbs()).toEqual(['media'])
    await click($$('[data-role="root"]')[1] ?? null)
    expect(crumbs()).toEqual(['out'])
  })

  it('chooses files with a click, Ctrl and Shift, and opens them', async () => {
    await mountDialog()
    const { chosen } = await open({ mode: 'files', multiple: true })
    await click(entry('a.mkv'))
    await click(entry('c.mkv'), { ctrlKey: true })
    expect(selected()).toEqual(['a.mkv', 'c.mkv'])
    await click(entry('c.mkv'), { ctrlKey: true })
    expect(selected()).toEqual(['a.mkv'])
    await click(entry('a.mkv'))
    await click(entry('d.mkv'), { shiftKey: true })
    expect(selected()).toEqual(['a.mkv', 'b.mp4', 'c.mkv', 'd.mkv'])
    expect($('[data-field="summary"]')?.textContent?.trim()).toBe('4 files selected')
    await click(entry('b.mp4'))
    expect(selected()).toEqual(['b.mp4'])
    await click($('[data-action="confirm"]'))
    expect(await chosen).toEqual(['/srv/media/b.mp4'])
    expect(currentRequest()).toBeNull()
  })

  it('takes one file at a time when only one may be chosen, and Enter opens it', async () => {
    await mountDialog()
    const { chosen } = await open({ mode: 'files', multiple: false })
    await click(entry('a.mkv'))
    await click(entry('c.mkv'), { ctrlKey: true })
    expect(selected()).toEqual(['c.mkv'])
    await click(entry('d.mkv'), { shiftKey: true })
    expect(selected()).toEqual(['d.mkv'])
    expect(list().getAttribute('aria-multiselectable')).toBeNull()
    await key('Home')
    await key('ArrowDown')
    await key('ArrowDown')
    // Enter opens the chosen file, not the one under the cursor.
    await key('Enter')
    expect(await chosen).toEqual(['/srv/media/d.mkv'])
  })

  it('works with the keyboard: arrows, Space, Shift+arrows, folders, Backspace and Enter', async () => {
    await mountDialog()
    const { chosen } = await open({ mode: 'files', multiple: true })
    await key('ArrowDown')
    await key('Enter')
    expect(crumbs()).toEqual(['media', 'season'])
    await key('Backspace')
    expect(crumbs()).toEqual(['media'])
    // Back in the parent, the cursor is on the folder it came from.
    expect(list().getAttribute('aria-activedescendant')).toBe(entry('season').id)
    await key('ArrowDown')
    await key(' ')
    await key('ArrowDown')
    await key('ArrowDown', { shiftKey: true })
    expect(selected()).toEqual(['a.mkv', 'b.mp4', 'c.mkv'])
    await key('End')
    await key(' ')
    expect(selected()).toEqual(['a.mkv', 'b.mp4', 'c.mkv', 'd.mkv'])
    await key('Home')
    await key('ArrowUp')
    expect(list().getAttribute('aria-activedescendant')).toBe(entry('extras').id)
    await key('ArrowDown')
    await key('ArrowDown')
    await key('Enter')
    expect(await chosen).toEqual([
      '/srv/media/a.mkv',
      '/srv/media/b.mp4',
      '/srv/media/c.mkv',
      '/srv/media/d.mkv',
    ])
  })

  it('selects every file with Ctrl+A and opens the cursor’s file when nothing is chosen', async () => {
    await mountDialog()
    const { chosen: first } = await open({ mode: 'files', multiple: true })
    await key('a', { ctrlKey: true })
    expect(selected()).toEqual(['a.mkv', 'b.mp4', 'c.mkv', 'd.mkv'])
    await click($('[data-action="cancel"]'))
    expect(await first).toBeNull()
    const { chosen: second } = await open({ mode: 'files', multiple: true })
    await settled()
    await key('End')
    await key('Enter')
    expect(await second).toEqual(['/srv/media/d.mkv'])
  })

  it('shows the server’s refusal of a path outside the roots and keeps the folder', async () => {
    await mountDialog()
    await open({ mode: 'files', multiple: true })
    const input = $<HTMLInputElement>('[data-field="location"]')
    if (input === null) throw new Error('no location field')
    input.value = '/etc'
    input.dispatchEvent(new Event('input'))
    $('form.file-browser__location')?.dispatchEvent(new Event('submit'))
    await settled()
    expect($('[data-state="problem"]')?.textContent).toContain(
      'The path is outside the allowed folders',
    )
    expect($('[data-state="problem"]')?.textContent).toContain('/etc is not inside')
    expect(crumbs()).toEqual(['media'])
    expect(names()).toContain('a.mkv')
    await click(entry('season'))
    expect($('[data-state="problem"]')).toBeNull()
  })

  it('shows only the filter’s files until the filter is turned off', async () => {
    await mountDialog()
    await open({ mode: 'files', multiple: true, filters: ['mp4'] })
    expect(names()).toEqual(['extras', 'season', 'b.mp4'])
    expect($('label[for$="-filter"]')?.textContent?.trim()).toBe('Only mp4')
    await click($('[data-field="filter"] input'))
    expect(names()).toEqual(['extras', 'season', 'a.mkv', 'b.mp4', 'c.mkv', 'd.mkv'])
  })

  it('has no filter switch without a filter', async () => {
    await mountDialog()
    await open({ mode: 'files', multiple: true })
    expect($('[data-field="filter"]')).toBeNull()
  })

  it('gives the folder shown in folder mode; its files cannot be chosen', async () => {
    await mountDialog()
    const { chosen } = await open({ mode: 'folder' })
    await click(entry('a.mkv'))
    expect(selected()).toEqual([])
    expect(entry('a.mkv').getAttribute('aria-disabled')).toBe('true')
    await click(entry('season'))
    expect($('[data-field="summary"]')?.textContent?.trim()).toBe('/srv/media/season')
    await click($('[data-action="confirm"]'))
    expect(await chosen).toEqual(['/srv/media/season'])
  })

  it('saves into the default path’s folder under its name, or a file’s name clicked', async () => {
    await mountDialog()
    const { chosen } = await open({ mode: 'save', defaultPath: '/srv/out/new.mkv' })
    expect(crumbs()).toEqual(['out'])
    expect($<HTMLInputElement>('[data-field="name"]')?.value).toBe('new.mkv')
    await click(entry('old.mkv'))
    expect($<HTMLInputElement>('[data-field="name"]')?.value).toBe('old.mkv')
    await click(entry('done'))
    await click($('[data-action="confirm"]'))
    expect(await chosen).toEqual(['/srv/out/done/old.mkv'])
  })

  it('starts saving in the first output root when the default path has no folder', async () => {
    await mountDialog()
    await open({ mode: 'save', defaultPath: 'new.mkv' })
    expect(crumbs()).toEqual(['out'])
  })

  it('starts where the last pick of the same kind ended, or at the root when that is gone', async () => {
    await mountDialog()
    const { chosen: first } = await open({ mode: 'files', multiple: true })
    await click(entry('season'))
    await click(entry('E01.mkv'))
    await click($('[data-action="confirm"]'))
    await first
    await open({ mode: 'files', multiple: true })
    expect(crumbs()).toEqual(['media', 'season'])
    await click($('[data-action="cancel"]'))
    delete tree['/srv/media/season']
    try {
      await open({ mode: 'files', multiple: true })
      await settled()
      expect(crumbs()).toEqual(['media'])
      expect($('[data-state="problem"]')).toBeNull()
    } finally {
      tree['/srv/media/season'] = {
        parent: '/srv/media',
        entries: [file('/srv/media/season/E01.mkv'), file('/srv/media/season/E02.mkv')],
      }
    }
  })

  it('gives nothing on Cancel or Escape, and the focus goes back to the opener', async () => {
    const { opener } = await mountDialog()
    const { chosen: cancelled } = await open({ mode: 'files', multiple: true })
    await click(entry('a.mkv'))
    await click($('[data-action="cancel"]'))
    expect(await cancelled).toBeNull()
    await settled()
    expect(document.activeElement).toBe(opener)

    const { chosen: escaped } = await open({ mode: 'files', multiple: true })
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape' }))
    await settled()
    expect(await escaped).toBeNull()
  })
})
