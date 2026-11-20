import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mountSettings, systemInfo } from '@/components/settings/testing'
import { platform } from '@/platform'
import type { DesktopShell } from '@/platform/types'
import { useSettingsStore } from '@/stores/settings'

import SettingsView from './SettingsView.vue'

// The naming editor has its own tests and asks for previews.
vi.mock('@/components/naming/NamingOptionsEditor.vue', () => ({
  default: { name: 'NamingOptionsEditor', props: ['disabled'], render: () => null },
}))

globalThis.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }) as unknown as MediaQueryList

// jsdom does not lay out, so it has no scrolling.
Element.prototype.scrollIntoView ??= () => undefined

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountView(options: { readOnly?: boolean; path?: string } = {}) {
  const result = await mountSettings(SettingsView, {
    path: options.path ?? '/settings',
    info: systemInfo({ mode: 'desktop', settings_read_only: options.readOnly ?? false }),
  })
  mounted.push(result.wrapper)
  return result
}

const CONTROLS = [
  '[data-field="hardware-tests"] input',
  '[data-field="sleep-inhibit"] input',
  '[data-field="notifications"] input',
  '[data-field="parallel-jobs"] input',
]

describe('the Settings view', () => {
  it('shows the sections in the order of the plan', async () => {
    const { wrapper } = await mountView()
    expect(
      wrapper.findAll('[data-section]').map((section) => section.attributes('data-section')),
    ).toEqual([
      'tools',
      'encoders',
      'output',
      'languages',
      'preview',
      'queue',
      'appearance',
      'diagnostics',
    ])
    expect(
      wrapper.find('[data-section="diagnostics"] [data-action="copy-diagnostics"]').exists(),
    ).toBe(true)
  })

  it('shows the desktop app’s own settings last, in the desktop app only', async () => {
    platform.desktop = {
      settings: async () => ({ tray: true }),
    } as Partial<DesktopShell> as DesktopShell
    try {
      const { wrapper } = await mountView()
      const sections = wrapper.findAll('[data-section]')
      expect(sections.at(-1)?.attributes('data-section')).toBe('desktop')
      expect(wrapper.find('[data-section-link="desktop"]').exists()).toBe(true)
      expect(wrapper.find('[data-field="tray"] input').element).toHaveProperty('checked', true)
    } finally {
      platform.desktop = null
    }
  })

  it.each([
    { appimage: '/a/Reframe.AppImage', sections: ['desktop', 'menu'] },
    { appimage: null, sections: ['diagnostics', 'desktop'] },
  ])('shows the application menu entry in the AppImage only ($appimage)', async (row) => {
    platform.desktop = {
      settings: async () => ({ tray: false }),
      menuEntry: async () => ({ appimage: row.appimage, added: true, other: null }),
    } as Partial<DesktopShell> as DesktopShell
    try {
      const { wrapper } = await mountView()
      await flushPromises()
      const sections = wrapper.findAll('[data-section]').map((s) => s.attributes('data-section'))
      expect(sections.slice(-2)).toEqual(row.sections)
      expect(wrapper.find('[data-section-link="menu"]').exists()).toBe(row.appimage !== null)
      expect(wrapper.findAll('[data-field="menu-entry"] input:checked')).toHaveLength(
        row.appimage === null ? 0 : 1,
      )
    } finally {
      platform.desktop = null
    }
  })

  it('shows read-only settings read-only, with a note', async () => {
    const { wrapper } = await mountView({ readOnly: true })
    expect(wrapper.find('[data-field="read-only"]').exists()).toBe(true)
    for (const selector of CONTROLS) {
      expect(wrapper.find(selector).attributes('disabled')).toBeDefined()
    }
    expect(
      wrapper.find('[data-tool="ffmpeg"] [data-field="override"]').attributes('readonly'),
    ).toBeDefined()
    expect(wrapper.findComponent({ name: 'NamingOptionsEditor' }).props('disabled')).toBe(true)
  })

  it('keeps the controls usable when the settings can be saved', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('[data-field="read-only"]').exists()).toBe(false)
    for (const selector of CONTROLS) {
      expect(wrapper.find(selector).attributes('disabled')).toBeUndefined()
    }
    expect(
      wrapper.find('[data-tool="ffmpeg"] [data-field="override"]').attributes('readonly'),
    ).toBeUndefined()
  })

  it('shows a loading note and no controls until the settings arrive', async () => {
    const { wrapper } = await mountView()
    const settings = useSettingsStore()
    const loaded = settings.settings
    settings.settings = null
    await flushPromises()
    expect(wrapper.find('.settings-view__loading').exists()).toBe(true)
    expect(wrapper.find('[data-section]').exists()).toBe(false)
    settings.settings = loaded
    await flushPromises()
    expect(wrapper.find('.settings-view__loading').exists()).toBe(false)
    expect(
      wrapper.find('[data-field="hardware-tests"] input').attributes('disabled'),
    ).toBeUndefined()
  })

  it('moves the focus to the Tools section for /settings#tools', async () => {
    await mountView({ path: '/settings#tools' })
    expect(document.activeElement?.id).toBe('settings-tools')
  })

  it('moves the focus to a section from its link, again on a second use', async () => {
    const { wrapper, router } = await mountView()
    await wrapper.find('[data-section-link="queue"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.hash).toBe('#queue')
    expect(document.activeElement?.id).toBe('settings-queue')
    ;(document.activeElement as HTMLElement).blur()
    await wrapper.find('[data-section-link="queue"]').trigger('click')
    await flushPromises()
    expect(document.activeElement?.id).toBe('settings-queue')
  })

  it('marks no section link as the current page', async () => {
    const { wrapper } = await mountView({ path: '/settings#tools' })
    expect(wrapper.find('[aria-current]').exists()).toBe(false)
  })
})
