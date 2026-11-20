import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Schemas, SystemInfo } from '@/api/types'
import { platform } from '@/platform'
import type { DesktopMenuEntry, DesktopShell } from '@/platform/types'
import { useSystemStore } from '@/stores/system'

import { FIRST_RUN_KEY } from './firstRun'
import MenuEntryOffer from './MenuEntryOffer.vue'
import { mountShell } from './testing'

const OFFERED_KEY = 'reframe.menuEntry.offered'
const APPIMAGE = '/home/u/Apps/Reframe.AppImage'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  Object.assign(platform, { kind: 'web' })
  localStorage.clear()
})

const tool = (name: string) => ({ name, status: 'found' }) as Schemas['ToolInfo']

function tools(): SystemInfo {
  return {
    mode: 'desktop',
    tools: { ffmpeg: tool('ffmpeg'), ffprobe: tool('ffprobe') },
  } as SystemInfo
}

/** The shell's menu entry; `refuse` makes the next change fail with that reason. */
function fakeShell(entry: Partial<DesktopMenuEntry> = {}) {
  const state = {
    entry: { appimage: APPIMAGE, added: false, other: null, ...entry } as DesktopMenuEntry,
    sent: [] as boolean[],
    refuse: null as string | null,
  }
  const shell = {
    menuEntry: async () => state.entry,
    async setMenuEntry(add: boolean) {
      state.sent.push(add)
      if (state.refuse !== null) throw state.refuse
      state.entry = { ...state.entry, added: add }
      return state.entry
    },
  } as Partial<DesktopShell> as DesktopShell
  return { shell, state }
}

async function mountOffer(
  shell: DesktopShell,
  options: { firstRunSeen?: boolean; info?: SystemInfo | null } = {},
) {
  Object.assign(platform, { kind: 'desktop' })
  if (options.firstRunSeen ?? true) localStorage.setItem(FIRST_RUN_KEY, 'true')
  const { wrapper } = await mountShell(MenuEntryOffer, {
    props: { shell },
    setup: () => {
      useSystemStore().info = options.info === undefined ? tools() : options.info
    },
  })
  mounted.push(wrapper as VueWrapper)
  await flushPromises()
  return wrapper
}

const dialog = () => document.querySelector('[data-dialog="menu-entry"]')
const button = (action: string) =>
  document.querySelector<HTMLButtonElement>(`[data-action="${action}"]`)

describe('the AppImage’s menu entry offer', () => {
  it('asks once, naming the AppImage, and adds the entry on Add', async () => {
    const { shell, state } = fakeShell()
    await mountOffer(shell)
    expect(dialog()?.textContent).toContain(APPIMAGE)
    button('menu-entry-add')?.click()
    await flushPromises()
    expect(state.sent).toEqual([true])
    await vi.waitFor(() => expect(dialog()).toBeNull())
    expect(localStorage.getItem(OFFERED_KEY)).toBe('true')
  })

  it('remembers Not now and does not ask again', async () => {
    const { shell, state } = fakeShell()
    await mountOffer(shell)
    button('menu-entry-skip')?.click()
    await flushPromises()
    expect(state.sent).toEqual([])
    await vi.waitFor(() => expect(dialog()).toBeNull())
    expect(localStorage.getItem(OFFERED_KEY)).toBe('true')

    for (const wrapper of mounted.splice(0)) wrapper.unmount()
    await mountOffer(shell)
    await vi.waitFor(() => expect(dialog()).toBeNull())
  })

  it('says why when the entry cannot be added, and closes', async () => {
    const { shell, state } = fakeShell()
    state.refuse = 'Permission denied (os error 13)'
    await mountOffer(shell)
    button('menu-entry-add')?.click()
    await flushPromises()
    expect(dialog()?.textContent).toContain('Permission denied (os error 13)')
    expect(button('menu-entry-add')).toBeNull()
    button('menu-entry-skip')?.click()
    await flushPromises()
    await vi.waitFor(() => expect(dialog()).toBeNull())
  })

  it.each([
    { appimage: null },
    { added: true },
    { other: '/usr/share/applications/Reframe.desktop' },
  ])('does not ask with the entry %j', async (entry) => {
    await mountOffer(fakeShell(entry).shell)
    await vi.waitFor(() => expect(dialog()).toBeNull())
    expect(localStorage.getItem(OFFERED_KEY)).toBeNull()
  })

  it('waits for the first-run screen', async () => {
    await mountOffer(fakeShell().shell, { firstRunSeen: false })
    await vi.waitFor(() => expect(dialog()).toBeNull())
  })

  it('stays quiet when the shell does not answer', async () => {
    const shell = {
      menuEntry: async () => Promise.reject(new Error('not allowed')),
    } as Partial<DesktopShell> as DesktopShell
    await mountOffer(shell)
    await vi.waitFor(() => expect(dialog()).toBeNull())
  })
})
