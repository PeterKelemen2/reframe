import { flushPromises, type VueWrapper } from '@vue/test-utils'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import { afterEach, describe, expect, it } from 'vitest'

import { settle } from '@/api/testing/fakes'
import type { JobGeometry, JobSettings, JobTemplate } from '@/api/types'
import CropMagnifier from '@/components/crop/CropMagnifier.vue'
import { geometryOf, LETTERBOX, setUpCrop } from '@/components/dimensions/testing'
import { mountShell } from '@/components/shell/testing'
import { issue, sampleJob } from '@/editor/testing/samples'
import { useCropStore } from '@/stores/crop'
import { useEditorStore } from '@/stores/editor'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import DimensionsTab from './DimensionsTab.vue'

// jsdom has none; PrimeVue's Select listens to the orientation with one.
globalThis.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  }) as MediaQueryList
Element.prototype.scrollIntoView ??= () => {}

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

function jobWith(dimensions: Partial<NonNullable<JobSettings['dimensions']>>): JobSettings {
  const job = sampleJob()
  job.dimensions = { ...job.dimensions!, ...dimensions }
  return job
}

async function mountTab(options: { job?: JobSettings; geometry?: JobGeometry } = {}) {
  const setup = setUpCrop(options)
  const editor = useEditorStore()
  // The workspace starts the crop store before any file is opened.
  useCropStore()
  await editor.open('letterbox')
  await settle()
  setup.detections[0]?.resolve()
  await settle()
  const { wrapper } = await mountShell(DimensionsTab, { pinia: setup.pinia })
  mounted.push(wrapper)
  await flushPromises()
  return { ...setup, wrapper, editor }
}

/** The PrimeVue control of a field. */
function control(wrapper: VueWrapper, path: string, component: object, index = 0) {
  const found = wrapper
    .find(`[data-path="${path}"]`)
    .findAllComponents(component as never)
    .at(index) as unknown as VueWrapper
  return { emit: (value: unknown) => found.vm.$emit('update:modelValue', value) }
}

function header(wrapper: VueWrapper) {
  return wrapper.find('.pipeline-header__line')
}

describe('the Dimensions tab', () => {
  it('shows the pipeline header, amber for an upscale and red for an invalid value', async () => {
    const { wrapper, server } = await mountTab({
      geometry: geometryOf(LETTERBOX, {
        scaled_width: 1920,
        scaled_height: 1080,
        upscaled: true,
      }),
    })
    expect(header(wrapper).text()).toBe(
      'Source 320×180 (16:9, square) → Output 1920×1080 · 1.78:1 · square pixels',
    )
    expect(header(wrapper).attributes('data-tone')).toBe('warn')
    expect(wrapper.find('.pipeline-header__tone').text()).toContain('enlarged')

    useValidationStore().issues = [issue('dimensions.custom_par_missing', 'dimensions.custom_par')]
    await flushPromises()
    expect(header(wrapper).attributes('data-tone')).toBe('error')
    useValidationStore().issues = [issue('dimensions.crop_not_detected', 'dimensions.crop', 'info')]
    await flushPromises()
    expect(header(wrapper).attributes('data-tone')).toBe('warn')
    expect(server.count('POST /api/jobs/geometry')).toBeGreaterThan(0)
  })

  it("shows the automatic detection with its notes, and conservative's own line", async () => {
    const { wrapper, editor } = await mountTab()
    const line = () => wrapper.find('[data-line="detection"]').text()
    expect(line()).toBe('Detected 22 / 24 / 0 / 0 on 5 of 10 frames')
    expect(wrapper.find('.crop-section__notes').text()).toContain('The frames disagree')
    control(wrapper, 'dimensions.crop', SelectButton).emit('conservative')
    await settle()
    await flushPromises()
    expect(editor.get('/dimensions/crop/mode')).toBe('conservative')
    expect(line()).toBe('Black on every frame: 0 / 0 / 0 / 0 (10 frames)')
  })

  it('snaps a typed crop value with a note, and the input shows the stored value', async () => {
    const { wrapper, editor } = await mountTab({
      job: jobWith({ crop: { mode: 'manual', rect: { top: 0, bottom: 0, left: 0, right: 0 } } }),
    })
    expect(wrapper.findComponent(CropMagnifier).exists()).toBe(true)
    const top = wrapper.find('input[data-edge="top"]')
    // setValue sends `input` and then `change`, as a typed value and Enter do.
    await top.setValue('141')
    await flushPromises()
    expect(editor.get('/dimensions/crop/rect')).toEqual({ top: 140, bottom: 0, left: 0, right: 0 })
    expect((top.element as HTMLInputElement).value).toBe('140')
    expect(wrapper.find('[data-note="snap"]').text()).toBe('Top 141 → 140 (4:2:0 chroma grid)')

    // Typed again on the same value: the input still shows what is stored.
    await top.setValue('141')
    await flushPromises()
    expect((top.element as HTMLInputElement).value).toBe('140')
  })

  it('makes a crop value typed after leaving the field an undo step of its own', async () => {
    const { wrapper, editor } = await mountTab({
      job: jobWith({ crop: { mode: 'manual', rect: { top: 0, bottom: 0, left: 0, right: 0 } } }),
    })
    const top = wrapper.find('input[data-edge="top"]')
    await top.trigger('focus')
    await top.setValue('10')
    await top.trigger('blur')
    await top.trigger('focus')
    await top.setValue('20')
    await top.trigger('blur')
    await flushPromises()
    editor.undo()
    expect(editor.get('/dimensions/crop/rect/top')).toBe(10)
  })

  it('turns every control off with a note while the video is copied', async () => {
    const job = jobWith({
      crop: { mode: 'manual', rect: { top: 22, bottom: 24, left: 0, right: 0 } },
    })
    job.video = { ...job.video!, passthrough: true }
    const { wrapper } = await mountTab({ job })
    expect(wrapper.find('[data-state="locked"]').text()).toBe(
      'The video is copied unchanged, so these settings are not used. Turn off Video passthrough on the Video tab to change the picture.',
    )
    const controls = [SelectButton, ToggleSwitch, Select, InputNumber, InputText].flatMap(
      (component) => wrapper.findAllComponents(component as never) as unknown as VueWrapper[],
    )
    expect(controls.length).toBeGreaterThan(6)
    expect(
      controls.filter((found) => (found.props() as { disabled?: boolean }).disabled !== true),
    ).toEqual([])
    expect(wrapper.findComponent(CropMagnifier).exists()).toBe(false)
  })

  it('turns every control off with a note, and shows no detection, for a file without video', async () => {
    const { wrapper } = await mountTab({ geometry: { source: null, geometry: null } })
    expect(wrapper.find('[data-state="locked"]').text()).toBe(
      'These settings are off: there is no picture to change.',
    )
    expect(
      wrapper
        .findAllComponents(SelectButton)
        .filter((found) => (found.props() as { disabled?: boolean }).disabled !== true),
    ).toEqual([])
    expect(wrapper.find('[data-detection]').exists()).toBe(false)
  })

  it("says that a group's files are queued without a crop, and shows the shown file's detection", async () => {
    const { wrapper, editor } = await mountTab()
    editor.target = {
      kind: 'group',
      groupId: 'g1',
      sourceId: 'letterbox',
      job: editor.job!,
      template: {} as JobTemplate,
      presetId: null,
      overrides: {},
      scope: 'group',
    }
    await flushPromises()
    expect(wrapper.find('[data-line="group"]').text()).toBe(
      'In a group, Automatic and Conservative queue the files without a crop: their black bars are not detected. Choose Manual to crop every file the same way.',
    )
    expect(wrapper.find('[data-line="detection"]').text()).toBe(
      'This file: Detected 22 / 24 / 0 / 0 on 5 of 10 frames',
    )
  })

  it('shows the magnifier in manual mode only', async () => {
    const { wrapper } = await mountTab()
    expect(wrapper.findComponent(CropMagnifier).exists()).toBe(false)
    expect(wrapper.find('input[data-edge="top"]').exists()).toBe(false)
  })

  it('changes the orientation and the advanced settings, one undo step each', async () => {
    const { wrapper, editor } = await mountTab()
    control(wrapper, 'dimensions.rotate', SelectButton).emit(90)
    control(wrapper, 'dimensions.flip_horizontal', ToggleSwitch).emit(true)
    control(wrapper, 'dimensions.modulus', SelectButton).emit(16)
    control(wrapper, 'dimensions.scaler', Select).emit('bicubic')
    control(wrapper, 'dimensions.pixel_aspect', SelectButton).emit('custom')
    await flushPromises()
    expect(editor.job?.dimensions).toMatchObject({
      rotate: 90,
      flip_horizontal: true,
      modulus: 16,
      scaler: 'bicubic',
      pixel_aspect: 'custom',
      custom_par: { num: 1, den: 1 },
    })
    control(wrapper, 'dimensions.custom_par', InputNumber, 1).emit(3)
    await flushPromises()
    expect(editor.get('/dimensions/custom_par')).toEqual({ num: 1, den: 3 })
    for (let step = 0; step < 6; step += 1) editor.undo()
    expect(editor.job?.dimensions).toMatchObject({
      rotate: 0,
      flip_horizontal: false,
      modulus: 2,
      scaler: 'lanczos',
      pixel_aspect: 'square',
      custom_par: null,
    })
    expect(editor.canUndo).toBe(false)
  })

  it('sets the output size by mode, box and typed values', async () => {
    const { wrapper, editor } = await mountTab({
      geometry: geometryOf(LETTERBOX, { scaled_width: 320, scaled_height: 180 }),
    })
    control(wrapper, 'dimensions.size', Select, 1).emit('720p')
    await flushPromises()
    expect(editor.get('/dimensions/size')).toEqual({ mode: 'fit', width: 1280, height: 720 })
    control(wrapper, 'dimensions.size', Select, 1).emit('custom')
    await flushPromises()
    control(wrapper, 'dimensions.size', InputNumber, 1).emit(500)
    await flushPromises()
    expect(editor.get('/dimensions/size')).toEqual({ mode: 'fit', width: 1280, height: 500 })
    control(wrapper, 'dimensions.size', Select, 0).emit('width')
    await flushPromises()
    expect(editor.get('/dimensions/size')).toEqual({ mode: 'width', width: 320 })
    control(wrapper, 'dimensions.allow_upscaling', ToggleSwitch).emit(true)
    await flushPromises()
    expect(editor.get('/dimensions/allow_upscaling')).toBe(true)
  })

  it('opens the advanced part when one of its fields is asked for', async () => {
    const { wrapper } = await mountTab()
    const body = () => wrapper.find('[data-path="dimensions.modulus"]').element as HTMLElement
    expect(body().closest<HTMLElement>('.rf-section__body')?.style.display).toBe('none')
    useUiStore().reveal('dimensions.modulus')
    await flushPromises()
    expect(body().closest<HTMLElement>('.rf-section__body')?.style.display).toBe('')
  })
})
