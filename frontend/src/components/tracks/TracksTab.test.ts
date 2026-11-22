import { flushPromises, type VueWrapper } from '@vue/test-utils'
import DataTable from 'primevue/datatable'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import Slider from 'primevue/slider'
import InputNumber from 'primevue/inputnumber'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import { configureClient } from '@/api/client'
import { deferred, FakeServer } from '@/api/testing/fakes'
import type { CapabilitySnapshot, JobDraft, JobSettings, MediaSource } from '@/api/types'
import AudioTab from '@/components/editor/tabs/AudioTab.vue'
import SubtitlesTab from '@/components/editor/tabs/SubtitlesTab.vue'
import { mountShell } from '@/components/shell/testing'
import { issue, sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { templateOfPreset } from '@/stores/presets'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import { probedSource, trackDefinitions } from './testing'

const mounted: VueWrapper[] = []

beforeAll(() => {
  // jsdom lays nothing out; a revealed row scrolls itself into view.
  Element.prototype.scrollIntoView = () => {}
  // PrimeVue's popup menu asks for the breakpoint, which jsdom cannot answer.
  window.matchMedia ??= (() => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

let server: FakeServer

interface MountOptions {
  tab?: 'audio' | 'subtitles'
  source?: MediaSource | null
  job?: (job: JobSettings) => void
  fdk?: 'available' | 'unavailable'
}

async function mountTab(options: MountOptions = {}) {
  const job = sampleJob()
  options.job?.(job)
  server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(structuredClone(job)))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const source = options.source === undefined ? probedSource('multitrack') : options.source
  const { wrapper } = await mountShell(options.tab === 'subtitles' ? SubtitlesTab : AudioTab, {
    setup() {
      const system = useSystemStore()
      system.definitions = trackDefinitions()
      system.capabilities = {
        encoders: {
          aac: { id: 'aac', state: 'available', hardware: false },
          libfdk_aac: { id: 'libfdk_aac', state: options.fdk ?? 'unavailable', hardware: false },
        },
      } as unknown as CapabilitySnapshot
      if (source !== null) useSourcesStore().entries = [{ id: 'src', path: '/media/x.mkv', source }]
    },
  })
  mounted.push(wrapper)
  const editor = useEditorStore()
  await editor.open('src')
  await flushPromises()
  return { wrapper, editor }
}

function streamsOf(editor: ReturnType<typeof useEditorStore>): (number | null | undefined)[] {
  return (editor.job?.audio ?? []).map((track) => track.source_stream)
}

function row(wrapper: VueWrapper, path: string) {
  return wrapper.find(`[data-path="${path}"]`)
}

function control(
  wrapper: VueWrapper,
  path: string,
  component: object,
): VueWrapper<{ $props: Record<string, unknown> }> {
  const field = wrapper.find(`.rf-field[data-path="${path}"]`)
  return field.findComponent(component as never) as unknown as VueWrapper
}

function labels(wrapper: VueWrapper, path: string): string[] {
  return row(wrapper, path)
    .findAll('.rf-field label')
    .map((label) => label.text())
}

function encoderChoices(wrapper: VueWrapper): string[] {
  const options = control(wrapper, 'audio[0].encoder', Select).props().options as {
    value: string
  }[]
  return options.map((option) => option.value)
}

/** The accessible names of the row's comboboxes; `aria-labelledby` wins over `aria-label`. */
function comboboxNames(wrapper: VueWrapper, path: string): (string | null)[] {
  return row(wrapper, path)
    .findAll('[role="combobox"]')
    .map((combobox) => {
      const ids = combobox.attributes('aria-labelledby')
      if (!ids) return combobox.attributes('aria-label') ?? null
      return ids
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent?.trim() ?? '')
        .join(' ')
    })
}

function subtitle(source: number) {
  const track = sampleJob().subtitles![0]!
  return { ...track, source, metadata: { ...track.metadata!, default: false } }
}

describe('the output audio tracks', () => {
  it('adds the source track chosen from Add track, as one undo step', async () => {
    const { wrapper, editor } = await mountTab()
    await wrapper.find('[data-action="add"]').trigger('click')
    const item = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((element) =>
      element.textContent?.includes('2 · eng · AAC-LC 2.0 · English Stereo'),
    )
    item?.querySelector<HTMLElement>('a, .p-menu-item-link, .p-menu-item-content')?.click()
    await flushPromises()
    expect(streamsOf(editor)).toEqual([1, 2, 3, 2])
    editor.undo()
    expect(streamsOf(editor)).toEqual([1, 2, 3])
  })

  it('adds every source track without an output track with Add all, as one undo step', async () => {
    const { wrapper, editor } = await mountTab({ job: (job) => job.audio!.splice(1) })
    const addAll = wrapper.find('[data-action="add-all"]')
    await addAll.trigger('click')
    expect(streamsOf(editor)).toEqual([1, 2, 3])
    expect(addAll.attributes('disabled')).toBeDefined()
    editor.undo()
    expect(streamsOf(editor)).toEqual([1])
  })

  it('removes a track, and the focus goes to the remove button of the next one', async () => {
    const { wrapper, editor } = await mountTab()
    await row(wrapper, 'audio[0]').find('[data-action="remove"]').trigger('click')
    await flushPromises()
    expect(streamsOf(editor)).toEqual([2, 3])
    expect(document.activeElement?.closest('[data-path]')?.getAttribute('data-path')).toBe(
      'audio[0]',
    )
    expect((document.activeElement as HTMLElement).dataset.action).toBe('remove')
    editor.undo()
    expect(streamsOf(editor)).toEqual([1, 2, 3])
  })

  it('removes the track whose remove button was pressed, not another one', async () => {
    const { wrapper, editor } = await mountTab()
    await row(wrapper, 'audio[1]').find('[data-action="remove"]').trigger('click')
    await flushPromises()
    expect(streamsOf(editor)).toEqual([1, 3])
    editor.undo()
    expect(streamsOf(editor)).toEqual([1, 2, 3])
    expect(editor.canUndo).toBe(false)
  })

  it('moves a track with its buttons and keeps the focus on the moved track', async () => {
    const { wrapper, editor } = await mountTab()
    expect(row(wrapper, 'audio[0]').find('[data-move="up"]').attributes('disabled')).toBeDefined()
    expect(row(wrapper, 'audio[2]').find('[data-move="down"]').attributes('disabled')).toBeDefined()
    await row(wrapper, 'audio[0]').find('[data-move="down"]').trigger('click')
    await flushPromises()
    expect(streamsOf(editor)).toEqual([2, 1, 3])
    const focused = document.activeElement as HTMLElement
    expect(focused.closest('[data-path]')?.getAttribute('data-path')).toBe('audio[1]')
    expect(focused.dataset.move).toBe('down')
    await row(wrapper, 'audio[2]').find('[data-move="up"]').trigger('click')
    expect(streamsOf(editor)).toEqual([2, 3, 1])
    editor.undo()
    expect(streamsOf(editor)).toEqual([2, 1, 3])
  })

  it('moves a dragged track to where it was dropped', async () => {
    const { wrapper, editor } = await mountTab()
    const table = wrapper.findComponent(DataTable)
    table.vm.$emit('row-reorder', { dragIndex: 1, dropIndex: 1, value: [] })
    expect(editor.canUndo).toBe(false)
    table.vm.$emit('row-reorder', { dragIndex: 0, dropIndex: 2, value: [] })
    expect(streamsOf(editor)).toEqual([2, 3, 1])
    editor.undo()
    expect(streamsOf(editor)).toEqual([1, 2, 3])
  })

  it("takes the preset's tracks again with Reload from preset rules, as one undo step", async () => {
    const { wrapper, editor } = await mountTab()
    editor.patch([{ op: 'remove', path: '/audio/0' }])
    await wrapper.find('[data-action="reload"]').trigger('click')
    await flushPromises()
    const request = server.requests.findLast((sent) => sent.path === '/api/jobs/draft')
    expect(request?.body).toEqual({ source_id: 'src', preset_id: 'h265-mkv-1080p' })
    expect(streamsOf(editor)).toEqual([1, 2, 3])
    editor.undo()
    expect(streamsOf(editor)).toEqual([2, 3])
  })

  it('drops a reload whose answer comes after another job was opened', async () => {
    const { wrapper, editor } = await mountTab()
    const answer = deferred<JobDraft>()
    server.on('POST /api/jobs/draft', () => answer.promise)
    await wrapper.find('[data-action="reload"]').trigger('click')
    // The reload has asked when the server holds a second draft request.
    await vi.waitFor(() => expect(server.count('POST /api/jobs/draft')).toBe(2))
    server.on('POST /api/jobs/draft', () => sampleDraft())
    await editor.open('src')
    const silent = sampleJob()
    silent.audio = []
    answer.resolve(sampleDraft(silent))
    await flushPromises()
    expect(streamsOf(editor)).toEqual([1, 2, 3])
  })

  it('says so when the job has no audio track', async () => {
    const { wrapper } = await mountTab({ job: (job) => (job.audio = []) })
    expect(wrapper.find('[data-list="audio"] [data-state="empty"]').text()).toBe(
      'No audio tracks: the output will have no audio.',
    )
  })

  it("says so when the source's tracks are not known", async () => {
    const { wrapper } = await mountTab({ source: null })
    expect(wrapper.find('[data-state="no-source"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-list="audio"] .track-row')).toHaveLength(3)
  })
})

describe('an output audio track', () => {
  it('takes another source track with its flags, keeping its default flag', async () => {
    const { wrapper, editor } = await mountTab()
    control(wrapper, 'audio[0].source_stream', Select).vm.$emit('update:modelValue', 3)
    expect(editor.job?.audio?.[0]).toMatchObject({
      source_stream: 3,
      metadata: { commentary: true, default: true, name: null },
    })
    editor.undo()
    expect(editor.job?.audio?.[0]?.metadata?.name).toBe('Japanese 5.1')
  })

  it('changes the encoder in one undo step, with a bitrate the encoder can write', async () => {
    const { wrapper, editor } = await mountTab({
      job: (job) => (job.audio![0]!.bitrate = 1024),
    })
    control(wrapper, 'audio[0].encoder', Select).vm.$emit('update:modelValue', 'ac3')
    expect(editor.job?.audio?.[0]).toMatchObject({ encoder: 'ac3', bitrate: 224 })
    editor.undo()
    expect(editor.job?.audio?.[0]).toMatchObject({ encoder: 'aac', bitrate: 1024 })
  })

  it('offers libfdk_aac only when the build has it', async () => {
    const without = await mountTab()
    expect(encoderChoices(without.wrapper)).not.toContain('libfdk_aac')
    expect(encoderChoices(without.wrapper)).toContain('aac')
    const withFdk = await mountTab({ fdk: 'available' })
    expect(encoderChoices(withFdk.wrapper)).toContain('libfdk_aac')
  })

  it('makes a typed gain one undo step, ended when the field is left', async () => {
    const { wrapper, editor } = await mountTab()
    const gain = control(wrapper, 'audio[0].gain', InputNumber)
    gain.vm.$emit('update:modelValue', -1)
    gain.vm.$emit('update:modelValue', -12)
    gain.vm.$emit('blur', new FocusEvent('blur'))
    gain.vm.$emit('update:modelValue', 3)
    editor.undo()
    expect(editor.job?.audio?.[0]?.gain).toBe(-12)
    editor.undo()
    expect(editor.job?.audio?.[0]?.gain).toBe(0)
  })

  it('makes a DRC drag one undo step, ended when the handle is let go', async () => {
    const { wrapper, editor } = await mountTab()
    const drc = control(wrapper, 'audio[0].drc', Slider)
    drc.vm.$emit('update:modelValue', 0.5)
    drc.vm.$emit('update:modelValue', 1.5)
    drc.vm.$emit('slideend', { originalEvent: new Event('mouseup'), value: 1.5 })
    drc.vm.$emit('update:modelValue', 2)
    editor.undo()
    expect(editor.job?.audio?.[0]?.drc).toBe(1.5)
    editor.undo()
    expect(editor.job?.audio?.[0]?.drc).toBe(0)
  })

  it('sets the mixdown, sample rate, bitrate and loudness', async () => {
    const { wrapper, editor } = await mountTab()
    control(wrapper, 'audio[0].mixdown', Select).vm.$emit('update:modelValue', 'keep')
    control(wrapper, 'audio[0].samplerate', Select).vm.$emit('update:modelValue', '44100')
    control(wrapper, 'audio[0].bitrate', Select).vm.$emit('update:modelValue', '256')
    control(wrapper, 'audio[0].loudness', Select).vm.$emit('update:modelValue', 'ebu_r128')
    expect(editor.job?.audio?.[0]).toMatchObject({
      mixdown: null,
      samplerate: 44100,
      bitrate: 256,
      loudness: 'ebu_r128',
    })
    control(wrapper, 'audio[0].bitrate', Select).vm.$emit('update:modelValue', 'default')
    expect(editor.job?.audio?.[0]?.bitrate).toBeNull()
  })

  it('names each list by its label, not by its value', async () => {
    const { wrapper } = await mountTab()
    expect(comboboxNames(wrapper, 'audio[0]')).toEqual([
      'Source',
      'Encoder',
      'Mixdown',
      'Sample rate',
      'Bitrate',
      'Normalise loudness',
    ])
  })

  it('switches to a VBR quality for an encoder that has one', async () => {
    const { wrapper, editor } = await mountTab({
      job: (job) => (job.audio![0]!.encoder = 'libmp3lame'),
    })
    expect(labels(wrapper, 'audio[0]')).toContain('Bitrate')
    expect(labels(wrapper, 'audio[0]')).not.toContain('Quality')
    const mode = row(wrapper, 'audio[0]').findAllComponents(SelectButton)[1]!
    mode.vm.$emit('update:modelValue', 'quality')
    await nextTick()
    expect(editor.job?.audio?.[0]).toMatchObject({ bitrate: null, quality: 2 })
    expect(labels(wrapper, 'audio[0]')).toContain('Quality')
    expect(labels(wrapper, 'audio[0]')).not.toContain('Bitrate')
  })

  it("marks the rate mode when a file's override sets the rate member the mode hides", async () => {
    const { wrapper, editor } = await mountTab({
      job: (job) => (job.audio![0]!.encoder = 'libmp3lame'),
    })
    editor.target = {
      kind: 'group',
      groupId: 'g1',
      sourceId: 'src',
      job: editor.job!,
      template: templateOfPreset(samplePreset()),
      presetId: null,
      overrides: { src: [{ op: 'replace', path: '/job/audio/0/quality', value: null }] },
      scope: 'file',
    }
    await nextTick()
    expect(
      row(wrapper, 'audio[0]')
        .findAll('[data-action="override-menu"]')
        .map((dot) => dot.attributes('aria-label')),
    ).toEqual(['Rate control differs from the group'])
  })

  it('says a lossless encoder has no bitrate', async () => {
    const { wrapper } = await mountTab({ job: (job) => (job.audio![0]!.encoder = 'flac') })
    expect(row(wrapper, 'audio[0]').find('[data-note="lossless"]').exists()).toBe(true)
    expect(wrapper.find('.rf-field[data-path="audio[0].bitrate"]').exists()).toBe(false)
  })

  it('says a passthru track the container holds is copied, and turns its settings off', async () => {
    const { wrapper, editor } = await mountTab()
    control(wrapper, 'audio[0].action', SelectButton).vm.$emit('update:modelValue', 'passthru')
    await nextTick()
    const first = row(wrapper, 'audio[0]')
    expect(first.find('[data-note="copied"]').text()).toContain('AC-3')
    expect(control(wrapper, 'audio[0].mixdown', Select).props().disabled).toBe(true)
    expect(first.find('.rf-field[data-path="audio[0].encoder"] label').text()).toBe(
      'Fallback encoder',
    )
    editor.set('/output/container', 'webm')
    await nextTick()
    expect(first.find('[data-note="copied"]').exists()).toBe(false)
    expect(control(wrapper, 'audio[0].mixdown', Select).props().disabled).toBe(false)
  })

  it('shows issues at their fields, marks the row, and lists the others under it', async () => {
    const { wrapper } = await mountTab()
    useValidationStore().issues = [
      issue('container.codec_unsupported', 'audio[1].encoder', 'error'),
      issue('metadata.language_invalid', 'audio[1].metadata.language', 'warning'),
      issue('audio.elsewhere', 'audio[1]', 'warning'),
    ]
    await nextTick()
    const second = row(wrapper, 'audio[1]')
    expect(second.attributes('data-severity')).toBe('error')
    expect(row(wrapper, 'audio[0]').attributes('data-severity')).toBeUndefined()
    const field = second.find('.rf-field[data-path="audio[1].encoder"]')
    expect(field.classes()).toContain('rf-field--error')
    expect(field.text()).toContain('container.codec_unsupported at audio[1].encoder')
    const language = second.find('.rf-field[data-path="audio[1].metadata.language"]')
    expect(language.text()).toContain('metadata.language_invalid')
    const listed = second.find('.track-row__issues').text()
    expect(listed).toContain('audio.elsewhere')
    expect(listed).not.toContain('container.codec_unsupported')
    expect(listed).not.toContain('metadata.language_invalid')
  })

  it('is where a link to the track lands', async () => {
    const { wrapper } = await mountTab()
    useUiStore().reveal('audio[2]')
    await flushPromises()
    expect(document.activeElement?.closest('[data-path="audio[2]"]')).not.toBeNull()
    expect(row(wrapper, 'audio[2]').classes()).toContain('is-revealed')
  })
})

describe('an output subtitle track', () => {
  it("converts to the container's text format and offers the formats", async () => {
    const { wrapper, editor } = await mountTab({ tab: 'subtitles' })
    expect(wrapper.find('.rf-field[data-path="subtitles[0].convert_to"]').exists()).toBe(false)
    control(wrapper, 'subtitles[0].action', SelectButton).vm.$emit('update:modelValue', 'convert')
    await nextTick()
    expect(editor.job?.subtitles?.[0]).toMatchObject({ action: 'convert', convert_to: 'srt' })
    control(wrapper, 'subtitles[0].convert_to', Select).vm.$emit('update:modelValue', 'webvtt')
    expect(editor.job?.subtitles?.[0]?.convert_to).toBe('webvtt')
    editor.undo()
    editor.undo()
    expect(editor.job?.subtitles?.[0]).toMatchObject({ action: 'copy', convert_to: null })
  })

  it('names each list by its label, not by its value', async () => {
    const { wrapper } = await mountTab({ tab: 'subtitles' })
    control(wrapper, 'subtitles[0].action', SelectButton).vm.$emit('update:modelValue', 'convert')
    await nextTick()
    expect(comboboxNames(wrapper, 'subtitles[0]')).toEqual(['Source', 'Format'])
  })

  it('offers forced-only for a burned-in track', async () => {
    const { wrapper, editor } = await mountTab({ tab: 'subtitles' })
    expect(wrapper.find('.rf-field[data-path="subtitles[0].forced_only"]').exists()).toBe(false)
    control(wrapper, 'subtitles[0].action', SelectButton).vm.$emit('update:modelValue', 'burn')
    await nextTick()
    const forced = wrapper.find('.rf-field[data-path="subtitles[0].forced_only"] input')
    await forced.setValue(true)
    expect(editor.job?.subtitles?.[0]).toMatchObject({ action: 'burn', forced_only: true })
  })

  it('cannot convert a bitmap track', async () => {
    const { wrapper } = await mountTab({
      tab: 'subtitles',
      source: probedSource('pgs'),
      job: (job) => (job.subtitles = [subtitle(1)]),
    })
    const options = control(wrapper, 'subtitles[0].action', SelectButton).props().options as {
      value: string
      disabled: boolean
    }[]
    expect(options.find((option) => option.value === 'convert')?.disabled).toBe(true)
    expect(options.find((option) => option.value === 'burn')?.disabled).toBe(false)
  })

  it('says a copied text track is converted when the container cannot hold it', async () => {
    const { wrapper, editor } = await mountTab({ tab: 'subtitles' })
    expect(wrapper.find('[data-note="converted"]').exists()).toBe(false)
    editor.set('/output/container', 'mp4')
    await nextTick()
    expect(wrapper.find('[data-note="converted"]').text()).toBe(
      'MP4 cannot hold SRT subtitles: they are converted to mov_text.',
    )
  })

  it('adds the source subtitle tracks without an output track with Add all', async () => {
    const { wrapper, editor } = await mountTab({ tab: 'subtitles' })
    await wrapper.find('[data-list="subtitles"] [data-action="add-all"]').trigger('click')
    expect(editor.job?.subtitles?.map((track) => track.source)).toEqual([4, 5, 6])
    expect(editor.job?.subtitles?.[1]?.metadata).toMatchObject({ hearing_impaired: true })
  })
})

describe('the numbers of an output audio track', () => {
  // Only English ships; a German locale shows the values that `toFixed` or `String` would
  // write the English way.
  it('are written in the app’s locale: DRC, sample rates and gain', async () => {
    const { wrapper, editor } = await mountTab()
    editor.set('/audio/0/action', 'encode')
    editor.set('/audio/0/encoder', 'aac')
    editor.set('/audio/0/drc', 1.5)
    editor.set('/audio/0/gain', -1.5)
    ;(wrapper.vm as unknown as { $i18n: { locale: string } }).$i18n.locale = 'de'
    await flushPromises()
    expect(wrapper.find('[data-path="audio[0].drc"] output').text()).toBe('1,5')
    const rates = control(wrapper, 'audio[0].samplerate', Select).props().options as {
      label: string
    }[]
    expect(rates.map((rate) => rate.label)).toContain('44,1\u00a0kHz')
    const gain = wrapper.find<HTMLInputElement>('[data-path="audio[0].gain"] input')
    expect(gain.element.value).toBe('-1,5 dB')
  })
})
