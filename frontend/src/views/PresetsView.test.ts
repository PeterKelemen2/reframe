import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { JobSettings, JobTemplate, Preset } from '@/api/types'
import { stubDom } from '@/components/naming/testing/samples'
import { nameConflict, preset, presetList, userPreset } from '@/components/presets/testing'
import { mountShell } from '@/components/shell/testing'
import { sampleDefinitions } from '@/components/summary/testing'
import { sampleJob } from '@/editor/testing/samples'
import { templateOfPreset } from '@/stores/presets'
import { useSystemStore } from '@/stores/system'

import PresetsView from './PresetsView.vue'

const download = vi.hoisted(() => vi.fn<(blob: Blob, name: string) => void>())
vi.mock('@/components/presets/format', async (original) => ({
  ...(await original<object>()),
  download,
}))

const editor = reactive({
  job: null as JobSettings | null,
  presetId: null as string | null,
  currentTemplate: null as JobTemplate | null,
  applyPreset: vi.fn<(id: string) => Promise<void>>(async () => {}),
  refreshPresetChanges: vi.fn<() => void>(),
  overriddenAt: () => false,
})
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))

const H265 = preset('h265-mkv-1080p', 'H.265 MKV 1080p', { category: 'Matroska' })
const FAST = preset('fast-1080p30', 'Fast 1080p30', { category: 'General' })
const MINE = userPreset('u1', 'Mine')
const OTHER = userPreset('u2', 'Other')

let server: FakeServer
const mounted: { unmount(): void }[] = []

beforeAll(stubDom)

beforeEach(() => {
  server = new FakeServer().on('GET /api/presets', presetList([FAST, H265, MINE, OTHER]))
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  editor.job = null
  editor.presetId = null
  editor.currentTemplate = null
  vi.clearAllMocks()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountView(query = '') {
  const result = await mountShell(PresetsView, {
    path: `/presets${query}`,
    setup: () => (useSystemStore().definitions = sampleDefinitions()),
  })
  mounted.push(result.wrapper)
  await flushPromises()
  return result
}

function openJob(with_: Preset): void {
  editor.job = { ...sampleJob(), preset_id: with_.id }
  editor.presetId = with_.id
  editor.currentTemplate = templateOfPreset(with_)
}

async function click(selector: string): Promise<void> {
  const element = document.body.querySelector<HTMLElement>(selector)
  if (element === null) throw new Error(`no ${selector}`)
  element.click()
  await flushPromises()
}

function focusAndClick(selector: string): Promise<void> {
  document.querySelector<HTMLElement>(selector)?.focus()
  return click(selector)
}

function details(): string | undefined {
  return document.querySelector<HTMLElement>('.preset-details')?.dataset.preset
}

function requests(method: string) {
  return server.requests.filter((request) => request.method === method)
}

describe('the presets view', () => {
  it('reads the presets each time it opens and shows the preset of the address', async () => {
    await mountView('?preset=u1')
    expect(server.count('GET /api/presets')).toBe(1)
    expect(details()).toBe('u1')
  })

  it('shows the open job’s preset, else the default', async () => {
    await mountView()
    expect(details()).toBe('h265-mkv-1080p')
    for (const wrapper of mounted.splice(0)) wrapper.unmount()
    openJob(FAST)
    await mountView()
    expect(details()).toBe('fast-1080p30')
  })

  it('sums up what a preset does: container, video, size, audio, subtitles', async () => {
    const subtitles = {
      selection: { languages: ['eng', 'hun'], tracks_per_language: 'all' },
      foreign_audio_search: true,
      burn_in: 'foreign_audio',
    } as Preset['subtitle_defaults']
    server.on('GET /api/presets', presetList([{ ...H265, subtitle_defaults: subtitles }]))
    await mountView('?preset=h265-mkv-1080p')
    const rows = [...document.querySelectorAll('.preset-details__summary .rf-kv')].map((row) => [
      row.querySelector('dt')?.textContent,
      row.querySelector('dd')?.textContent?.trim(),
    ])
    expect(rows).toEqual([
      ['Category', 'Matroska'],
      ['Container', 'Matroska (MKV)'],
      ['Video', 'x265, RF 22'],
      ['Size', 'Fit within 1920×1080'],
      ['Audio tracks', 'The first track per language · the preferred languages of Settings'],
      ['Audio encoding', 'AAC · Stereo · up to 160 kb/s'],
      ['Subtitle tracks', 'Every track per language · eng, hun'],
      ['Burn in', 'Foreign audio subtitles'],
    ])
  })

  it('keeps built-ins locked: no rename, update or delete', async () => {
    const { wrapper } = await mountView('?preset=h265-mkv-1080p')
    expect(wrapper.find('[data-badge="built-in"]').exists()).toBe(true)
    for (const action of ['rename', 'update', 'delete']) {
      expect(wrapper.find(`.preset-details__${action}`).exists()).toBe(false)
    }
    expect(wrapper.find('.preset-details__duplicate').exists()).toBe(true)
  })

  it('duplicates a built-in as a user preset under the free name the server offers', async () => {
    const copy = userPreset('u3', 'H.265 MKV 1080p (2)')
    let posts = 0
    server.on('POST /api/presets', () => {
      posts += 1
      return posts === 1
        ? nameConflict('H.265 MKV 1080p', 'H.265 MKV 1080p (2)')
        : new Response(JSON.stringify(copy), { status: 201 })
    })
    await mountView('?preset=h265-mkv-1080p')
    await click('.preset-details__duplicate')
    expect(requests('POST').map((request) => request.body)).toEqual([
      {
        template: templateOfPreset(H265),
        name: 'H.265 MKV 1080p',
        category: 'Custom',
        description: H265.description,
      },
      {
        template: templateOfPreset(H265),
        name: 'H.265 MKV 1080p (2)',
        category: 'Custom',
        description: H265.description,
      },
    ])
    expect(details()).toBe('u3')
  })

  it('renames a user preset', async () => {
    server.on('PUT /api/presets/u1', (request) => request.body)
    await mountView('?preset=u1')
    await click('.preset-details__rename')
    const input = document.querySelector<HTMLInputElement>('.preset-name-dialog__name')!
    expect(input.value).toBe('Mine')
    input.value = 'Renamed'
    input.dispatchEvent(new Event('input'))
    await flushPromises()
    await click('.preset-name-dialog__submit')
    expect(requests('PUT').map((request) => request.body)).toEqual([{ ...MINE, name: 'Renamed' }])
    expect(document.querySelector('.preset-details__name')?.textContent).toBe('Renamed')
  })

  it('deletes a user preset with Delete in the tree, only after the confirmation', async () => {
    server.on('DELETE /api/presets/u2', OTHER)
    const { wrapper } = await mountView('?preset=u2')
    const item = wrapper.find('.preset-tree [data-preset="u2"]').element as HTMLElement
    item.focus()
    item.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true }))
    await flushPromises()
    expect(document.querySelector('.presets-view__confirm-text')?.textContent).toContain('“Other”')
    expect(requests('DELETE')).toEqual([])
    await click('.presets-view__confirm-button')
    expect(requests('DELETE').map((request) => request.path)).toEqual(['/api/presets/u2'])
    expect(wrapper.find('.preset-tree [data-preset="u2"]').exists()).toBe(false)
  })

  it('deletes nothing when the confirmation is cancelled', async () => {
    await mountView('?preset=u2')
    await click('.preset-details__delete')
    const cancel = [
      ...document.querySelectorAll<HTMLElement>('.presets-view__confirm button'),
    ].find((button) => button.textContent?.includes('Cancel'))
    cancel?.click()
    await flushPromises()
    expect(requests('DELETE')).toEqual([])
  })

  it('makes a preset the default and moves the star', async () => {
    server.on('POST /api/presets/u1/default', MINE)
    const { wrapper } = await mountView('?preset=u1')
    await click('.preset-details__default')
    expect(requests('POST').map((request) => request.path)).toEqual(['/api/presets/u1/default'])
    expect(wrapper.find('.preset-tree [data-preset="u1"]').text()).toContain('Default')
    expect(wrapper.find('.preset-tree [data-preset="h265-mkv-1080p"]').text()).not.toContain(
      'Default',
    )
  })

  it('applies a preset to the open job and goes back to the workspace', async () => {
    openJob(H265)
    const { router } = await mountView('?preset=fast-1080p30')
    await click('.preset-details__apply')
    expect(editor.applyPreset).toHaveBeenCalledExactlyOnceWith('fast-1080p30')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('workspace'))
  })

  it('cannot apply or update without an open job', async () => {
    const { wrapper } = await mountView('?preset=u1')
    expect(wrapper.find('.preset-details__apply').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.preset-details__update').attributes('disabled')).toBeDefined()
  })

  it('updates the open job’s own preset at once, another one only after a confirmation', async () => {
    openJob(MINE)
    editor.currentTemplate = { ...templateOfPreset(MINE), crop_policy: 'fixed' }
    server
      .on('PUT /api/presets/u1', (request) => request.body)
      .on('PUT /api/presets/u2', (request) => request.body)
    await mountView('?preset=u1')
    await click('.preset-details__update')
    expect(requests('PUT').map((request) => request.body)).toEqual([
      { ...MINE, crop_policy: 'fixed' },
    ])
    expect(editor.refreshPresetChanges).toHaveBeenCalledOnce()

    for (const wrapper of mounted.splice(0)) wrapper.unmount()
    await mountView('?preset=u2')
    await click('.preset-details__update')
    expect(requests('PUT')).toHaveLength(1)
    await click('.presets-view__confirm-button')
    expect(requests('PUT').at(-1)?.body).toEqual({ ...OTHER, crop_policy: 'fixed' })
  })

  describe('keeps the keyboard focus on the page', () => {
    it('after Duplicate: on the copy in the tree', async () => {
      server.on('POST /api/presets', userPreset('u3', 'Mine (2)'))
      await mountView('?preset=u1')
      await focusAndClick('.preset-details__duplicate')
      await flushPromises()
      expect(document.activeElement).toBe(document.querySelector('.preset-tree [data-preset="u3"]'))
    })

    it('after a deletion: on the preset shown instead, in the tree', async () => {
      server.on('DELETE /api/presets/u2', OTHER)
      await mountView('?preset=u2')
      await focusAndClick('.preset-details__delete')
      await click('.presets-view__confirm-button')
      expect(details()).toBe('h265-mkv-1080p')
      await vi.waitFor(() =>
        expect(document.activeElement).toBe(
          document.querySelector('.preset-tree [data-preset="h265-mkv-1080p"]'),
        ),
      )
    })

    it('after Make default: on its button, now unavailable', async () => {
      server.on('POST /api/presets/u1/default', MINE)
      await mountView('?preset=u1')
      await focusAndClick('.preset-details__default')
      const button = document.querySelector<HTMLButtonElement>('.preset-details__default')
      expect(document.activeElement).toBe(button)
      expect(button?.getAttribute('aria-disabled')).toBe('true')
    })

    it('after Use for the open job: in the workspace', async () => {
      openJob(H265)
      const tab = Object.assign(document.createElement('button'), { className: 'workspace-tab' })
      tab.setAttribute('role', 'tab')
      tab.setAttribute('aria-selected', 'true')
      const tabs = Object.assign(document.createElement('div'), { className: 'editor-tabs' })
      tabs.append(tab)
      const { router } = await mountView('?preset=fast-1080p30')
      document.body.append(tabs)
      await focusAndClick('.preset-details__apply')
      await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('workspace'))
      await flushPromises()
      expect(document.activeElement).toBe(tab)
    })
  })

  it('exports one preset under its name, and every user preset', async () => {
    server.on('GET /api/presets/export', { document: { presets: [] }, issues: [] })
    await mountView('?preset=u1')
    await click('.preset-details__export')
    await click('.presets-view__export-all')
    expect(
      requests('GET')
        .filter((r) => r.path === '/api/presets/export')
        .map((r) => r.search),
    ).toEqual(['?ids=u1', '?ids=u1&ids=u2'])
    expect(download.mock.calls.map(([, name]) => name)).toEqual([
      'Mine.json',
      'reframe-presets.json',
    ])
  })
})
