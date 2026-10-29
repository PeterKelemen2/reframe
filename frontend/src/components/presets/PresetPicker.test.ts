import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { FieldChange, JobSettings, JobTemplate, JsonPatchOp, Preset } from '@/api/types'
import { sampleJob } from '@/editor/testing/samples'
import { stubDom } from '@/components/naming/testing/samples'
import { mountShell } from '@/components/shell/testing'
import { templateOfPreset } from '@/stores/presets'

import PresetPicker from './PresetPicker.vue'
import { nameConflict, preset, presetList, userPreset } from './testing'

const H265 = preset('h265-mkv-1080p', 'H.265 MKV 1080p', { category: 'Matroska' })
const FAST = preset('fast-1080p30', 'Fast 1080p30', { category: 'General' })
const MINE = userPreset('u1', 'Mine')

// A double of the editor store: the picker reads the job's preset and its changes from it.
const editor = reactive({
  job: null as JobSettings | null,
  presetId: null as string | null,
  preset: null as Preset | null,
  currentTemplate: null as JobTemplate | null,
  presetChanges: [] as FieldChange[],
  loading: false,
  applyPreset: vi.fn<(id: string) => Promise<void>>(async () => {}),
  patch: vi.fn<(ops: JsonPatchOp[]) => void>(),
  refreshPresetChanges: vi.fn<() => void>(),
})
vi.mock('@/stores/editor', () => ({ useEditorStore: () => editor }))

let server: FakeServer
const mounted: { unmount(): void }[] = []

function openJob(with_: Preset, changes: FieldChange[] = []): void {
  editor.job = { ...sampleJob(), preset_id: with_.id, preset_name: with_.name }
  editor.presetId = with_.id
  editor.preset = with_
  editor.currentTemplate = {
    ...templateOfPreset(with_),
    video: { ...with_.video!, encoder: 'libx264' },
  }
  editor.presetChanges = changes
}

beforeAll(stubDom)

beforeEach(() => {
  server = new FakeServer().on('GET /api/presets', presetList([FAST, H265, MINE]))
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  editor.job = null
  editor.presetId = null
  editor.preset = null
  editor.currentTemplate = null
  editor.presetChanges = []
  editor.loading = false
  vi.clearAllMocks()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountPicker() {
  const result = await mountShell(PresetPicker)
  mounted.push(result.wrapper)
  await flushPromises()
  return result
}

function body(): HTMLElement {
  return document.body
}

async function click(selector: string): Promise<void> {
  const element = body().querySelector<HTMLElement>(selector)
  if (element === null) throw new Error(`no ${selector}`)
  element.click()
  await flushPromises()
}

const ENCODER_CHANGE: FieldChange = {
  path: 'video.encoder',
  kind: 'changed',
  preset_value: 'libx265',
  value: 'libx264',
}

describe('the preset picker', () => {
  it('cannot be used before a source is open', async () => {
    const { wrapper } = await mountPicker()
    expect(wrapper.find('.preset-picker__trigger').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-field="preset"]').text()).toBe('Open a source first')
  })

  it('shows the job’s preset, and the job’s own name for a preset that was deleted', async () => {
    openJob(H265)
    const { wrapper } = await mountPicker()
    expect(wrapper.find('[data-field="preset"]').text()).toBe('H.265 MKV 1080p')
    expect(wrapper.find('[data-state="missing"]').exists()).toBe(false)

    editor.job = { ...sampleJob(), preset_id: 'gone', preset_name: 'Gone preset' }
    editor.presetId = 'gone'
    editor.preset = null
    await flushPromises()
    expect(wrapper.find('[data-field="preset"]').text()).toBe('Gone preset')
    expect(wrapper.find('[data-state="missing"]').exists()).toBe(true)
  })

  it('drafts the job again with the preset chosen from the list, by category', async () => {
    openJob(H265)
    const { wrapper } = await mountPicker()
    await wrapper.find('.preset-picker__trigger').trigger('click')
    await flushPromises()
    const groups = [...body().querySelectorAll('.preset-picker__group')].map((g) => g.textContent)
    expect(groups).toEqual(['General', 'Matroska', 'Custom'])
    // Opening the list reads it again: another front end may have changed it.
    expect(server.count('GET /api/presets')).toBe(2)
    await click('[data-preset="fast-1080p30"]')
    expect(editor.applyPreset).toHaveBeenCalledExactlyOnceWith('fast-1080p30')
  })

  it('does not draft again for the preset the job has', async () => {
    openJob(H265)
    const { wrapper } = await mountPicker()
    await wrapper.find('.preset-picker__trigger').trigger('click')
    await flushPromises()
    await click('[data-preset="h265-mkv-1080p"]')
    expect(editor.applyPreset).not.toHaveBeenCalled()
  })

  it('shows the modified marker only while the job differs, and its popover lists the changes in words', async () => {
    openJob(H265)
    const { wrapper } = await mountPicker()
    expect(wrapper.find('.preset-picker__modified').exists()).toBe(false)

    editor.presetChanges = [
      ENCODER_CHANGE,
      {
        path: 'audio_defaults.codec_rules[0].max_bitrate',
        kind: 'changed',
        preset_value: 160,
        value: 192,
      },
      { path: 'filters.denoise', kind: 'added', preset_value: null, value: { preset: 'light' } },
    ]
    await flushPromises()
    await wrapper.find('.preset-picker__modified').trigger('click')
    await flushPromises()
    const rows = [...body().querySelectorAll('.preset-changes__item')].map((row) => ({
      field: row.querySelector('.preset-changes__field')?.textContent,
      before: row.querySelector('.preset-changes__before')?.textContent,
      after: row.querySelector('.preset-changes__after')?.textContent,
      values: row.querySelector('.preset-changes__values')?.textContent?.trim(),
    }))
    expect(rows.map(({ field, before, after }) => [field, before, after])).toEqual([
      ['Video › Encoder', 'libx265', 'libx264'],
      ['Audio defaults › Codec rule 1 › Maximum bitrate', '160', '192'],
      ['Filters › Denoise', undefined, undefined],
    ])
    expect(rows[2]?.values).toBe('Added: {"preset":"light"}')
  })

  it('saves the current settings as a new preset, and the job then follows it in one undo step', async () => {
    openJob(H265, [ENCODER_CHANGE])
    const created = userPreset('u2', 'My x264')
    server.on('POST /api/presets', () => new Response(JSON.stringify(created), { status: 201 }))
    const { wrapper } = await mountPicker()
    await wrapper.find('.preset-picker__modified').trigger('click')
    await flushPromises()
    await click('.preset-picker__save-as')
    const input = body().querySelector<HTMLInputElement>('.preset-name-dialog__name')!
    input.value = 'My x264'
    input.dispatchEvent(new Event('input'))
    await flushPromises()
    await click('.preset-name-dialog__submit')

    expect(server.requests.at(-1)?.body).toEqual({
      template: editor.currentTemplate,
      name: 'My x264',
      category: 'Custom',
      description: '',
    })
    expect(editor.patch).toHaveBeenCalledExactlyOnceWith([
      { op: 'replace', path: '/preset_id', value: 'u2' },
      { op: 'replace', path: '/preset_name', value: 'My x264' },
    ])
  })

  it('shows a name clash at the name and takes the free name the server offers', async () => {
    openJob(H265, [ENCODER_CHANGE])
    server.on('POST /api/presets', () => nameConflict('Mine', 'mine (2)'))
    const { wrapper } = await mountPicker()
    await wrapper.find('.preset-picker__modified').trigger('click')
    await flushPromises()
    await click('.preset-picker__save-as')
    const input = body().querySelector<HTMLInputElement>('.preset-name-dialog__name')!
    input.value = 'mine'
    input.dispatchEvent(new Event('input'))
    await flushPromises()
    await click('.preset-name-dialog__submit')

    expect(body().querySelector('.preset-name-dialog .rf-field__issues')?.textContent).toContain(
      'A preset named “Mine” already exists.',
    )
    expect(editor.patch).not.toHaveBeenCalled()
    await click('.preset-name-dialog__offered')
    expect(body().querySelector<HTMLInputElement>('.preset-name-dialog__name')?.value).toBe(
      'mine (2)',
    )
  })

  it('updates a user preset with the current settings and asks for the changes again', async () => {
    openJob(MINE, [ENCODER_CHANGE])
    server.on('PUT /api/presets/u1', (request) => request.body)
    const { wrapper } = await mountPicker()
    await wrapper.find('.preset-picker__modified').trigger('click')
    await flushPromises()
    await click('.preset-picker__update')

    const sent = server.requests.at(-1)
    expect(sent?.method).toBe('PUT')
    expect(sent?.body).toEqual({
      ...editor.currentTemplate,
      id: 'u1',
      name: 'Mine',
      category: 'Custom',
      description: MINE.description,
      built_in: false,
    })
    expect(editor.refreshPresetChanges).toHaveBeenCalledOnce()
  })

  it('offers no update for a built-in preset', async () => {
    openJob(H265, [ENCODER_CHANGE])
    const { wrapper } = await mountPicker()
    await wrapper.find('.preset-picker__modified').trigger('click')
    await flushPromises()
    expect(body().querySelector('.preset-picker__update')).toBeNull()
    expect(body().querySelector('.preset-picker__locked')).not.toBeNull()
  })

  it('opens the presets view at the job’s preset', async () => {
    openJob(MINE, [ENCODER_CHANGE])
    const { wrapper, router } = await mountPicker()
    await wrapper.find('.preset-picker__modified').trigger('click')
    await flushPromises()
    await click('.preset-picker__open')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('presets'))
    expect(router.currentRoute.value.query).toEqual({ preset: 'u1' })
  })
})
