import { flushPromises, type VueWrapper } from '@vue/test-utils'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import { afterEach, describe, expect, it } from 'vitest'

import type { JobSettings } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import EncoderPicker from '@/components/video/EncoderPicker.vue'
import QualitySlider from '@/components/video/QualitySlider.vue'
import SpeedPresetSlider from '@/components/video/SpeedPresetSlider.vue'
import { openJob, setUpVideo, snapshot, withStatus } from '@/components/video/testing'
import { sampleJob } from '@/editor/testing/samples'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

import VideoTab from './VideoTab.vue'

const mounted: { unmount(): void }[] = []

// jsdom lays nothing out; a revealed field scrolls itself into view.
Element.prototype.scrollIntoView ??= () => undefined

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  localStorage.clear()
})

async function mountTab(options: Parameters<typeof setUpVideo>[0] & { geometry?: unknown } = {}) {
  const setup = setUpVideo(options)
  if (options.geometry !== undefined) setup.server.on('POST /api/jobs/geometry', options.geometry)
  await openJob()
  const { wrapper } = await mountShell(VideoTab, { pinia: setup.pinia })
  mounted.push(wrapper)
  await flushPromises()
  return { ...setup, wrapper }
}

function jobWith(video: Partial<NonNullable<JobSettings['video']>>): JobSettings {
  const job = sampleJob()
  job.video = { ...job.video!, ...video }
  return job
}

function field(wrapper: VueWrapper, path: string) {
  return wrapper.find(`[data-path="${path}"]`)
}

/** The PrimeVue control of a field, with its props as plain values. */
function control(wrapper: VueWrapper, path: string, component: object) {
  const found = field(wrapper, path).findComponent(component as never) as unknown as VueWrapper
  return {
    prop: (name: string) => (found.props() as Record<string, unknown>)[name],
    emit: (value: unknown) => found.vm.$emit('update:modelValue', value),
  }
}

describe('the Video tab', () => {
  it('switches the encoder in one undo step, converting what does not fit', async () => {
    const { wrapper, editor } = await mountTab()
    const before = JSON.stringify(editor.job)
    wrapper.findComponent(EncoderPicker).vm.$emit('update:modelValue', 'hevc_amf')
    await flushPromises()
    expect(editor.job?.video).toMatchObject({
      encoder: 'hevc_amf',
      // RF 22 on hevc_amf's CQ scale (its table in the definitions).
      rate_control: { mode: 'quality', value: 25 },
      preset: null,
      profile: 'main10',
      bit_depth: 10,
      fast_decode: false,
      custom_params: '',
    })
    expect(useToastStore().items.at(-1)).toMatchObject({
      severity: 'info',
      summary: 'Custom parameters removed',
    })
    editor.undo()
    expect(JSON.stringify(editor.job)).toBe(before)
    expect(editor.canUndo).toBe(false)
  })

  it('turns every other video control off for passthrough, with a note', async () => {
    const { wrapper, editor } = await mountTab()
    expect(wrapper.find('[data-note="passthrough"]').exists()).toBe(false)
    control(wrapper, 'video.passthrough', ToggleSwitch).emit(true)
    await flushPromises()
    expect(editor.job?.video?.passthrough).toBe(true)
    expect(wrapper.find('[data-note="passthrough"]').exists()).toBe(true)
    expect(wrapper.findComponent(EncoderPicker).props('disabled')).toBe(true)
    expect(wrapper.findComponent(QualitySlider).props('disabled')).toBe(true)
    expect(wrapper.findComponent(SpeedPresetSlider).props('disabled')).toBe(true)
    expect(control(wrapper, 'video.framerate', Select).prop('disabled')).toBe(true)
    expect(control(wrapper, 'video.bit_depth', SelectButton).prop('disabled')).toBe(true)
    expect(control(wrapper, 'video.passthrough', ToggleSwitch).prop('disabled')).toBeFalsy()
  })

  it('makes one undo step of each quality drag', async () => {
    const { wrapper, editor } = await mountTab()
    const slider = wrapper.findComponent(QualitySlider)
    for (const value of [23, 24]) slider.vm.$emit('update:modelValue', value)
    slider.vm.$emit('commit')
    slider.vm.$emit('update:modelValue', 26)
    slider.vm.$emit('commit')
    const value = () => (editor.job!.video!.rate_control as { value: number }).value
    expect(value()).toBe(26)
    editor.undo()
    expect(value()).toBe(24)
    editor.undo()
    expect(value()).toBe(22)
    expect(editor.canUndo).toBe(false)
  })

  it('shades the band for the output size of the job', async () => {
    const { wrapper } = await mountTab({
      geometry: {
        source: { width: 3840, height: 2160 },
        geometry: { scaled_width: 1920, scaled_height: 1080 },
      },
    })
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(wrapper.findComponent(QualitySlider).props('band')).toMatchObject({ low: 20, high: 24 })
  })

  it('switches the rate control and brings the other mode back as it was', async () => {
    const { wrapper, editor } = await mountTab()
    editor.set('/video/rate_control/value', 18.5)
    const mode = () => control(wrapper, 'video.rate_control', SelectButton)
    mode().emit('bitrate')
    await flushPromises()
    expect(editor.job?.video?.rate_control).toEqual({
      mode: 'bitrate',
      kbps: 6000,
      two_pass: false,
      turbo_first_pass: false,
    })
    editor.set('/video/rate_control/kbps', 2500)
    mode().emit('quality')
    await flushPromises()
    expect(editor.job?.video?.rate_control).toEqual({ mode: 'quality', value: 18.5 })
    mode().emit('bitrate')
    await flushPromises()
    expect(editor.job?.video?.rate_control).toMatchObject({ mode: 'bitrate', kbps: 2500 })
  })

  it('turns turbo off with 2-pass, in one step', async () => {
    const rc = { mode: 'bitrate', kbps: 3000, two_pass: true, turbo_first_pass: true } as const
    const { wrapper, editor } = await mountTab({ job: jobWith({ rate_control: rc }) })
    control(wrapper, 'video.rate_control.two_pass', ToggleSwitch).emit(false)
    await flushPromises()
    expect(editor.job?.video?.rate_control).toMatchObject({
      two_pass: false,
      turbo_first_pass: false,
    })
    editor.undo()
    expect(editor.job?.video?.rate_control).toMatchObject({
      two_pass: true,
      turbo_first_pass: true,
    })
  })

  it('opens the advanced options and focuses them when the panel as a whole is asked for', async () => {
    const { wrapper } = await mountTab()
    const ui = useUiStore()
    ui.advancedOpen = false
    await flushPromises()
    ui.reveal('video.advanced')
    await flushPromises()
    expect(ui.advancedOpen).toBe(true)
    const section = wrapper.find('[data-section="advanced"]')
    expect(section.find('button').attributes('aria-expanded')).toBe('true')
    expect(document.activeElement).toBe(section.find('button').element)
  })

  it('offers 2-pass only where the encoder has it', async () => {
    const rc = { mode: 'bitrate', kbps: 3000, two_pass: false, turbo_first_pass: false } as const
    const { wrapper } = await mountTab({
      job: jobWith({ encoder: 'hevc_amf', rate_control: rc, custom_params: '' }),
    })
    expect(control(wrapper, 'video.rate_control.two_pass', ToggleSwitch).prop('disabled')).toBe(
      true,
    )
    expect(field(wrapper, 'video.rate_control.two_pass').text()).toContain('no 2-pass mode')
  })

  it("shows the encoder's own controls from the definitions", async () => {
    const x265 = await mountTab()
    for (const path of ['preset', 'tune', 'profile', 'level', 'fast_decode', 'bit_depth']) {
      expect.soft(field(x265.wrapper, `video.${path}`).exists()).toBe(true)
    }
    const vaapi = await mountTab({
      job: jobWith({ encoder: 'hevc_vaapi', preset: null, custom_params: '' }),
    })
    for (const path of ['preset', 'tune', 'fast_decode']) {
      expect.soft(field(vaapi.wrapper, `video.${path}`).exists()).toBe(false)
    }
    expect(field(vaapi.wrapper, 'video.profile').exists()).toBe(true)
    const h264 = await mountTab({
      job: jobWith({
        encoder: 'h264_amf',
        bit_depth: 8,
        profile: null,
        preset: null,
        custom_params: '',
      }),
    })
    expect(field(h264.wrapper, 'video.bit_depth').exists()).toBe(false)
  })

  it('offers only the profiles of the bit depth, and resets the profile with the depth', async () => {
    const { wrapper, editor } = await mountTab()
    const labels = () =>
      (control(wrapper, 'video.profile', Select).prop('options') as { label: string }[]).map(
        (option) => option.label,
      )
    expect(labels()).toEqual(['Main 10 (default)', 'Main 10'])
    control(wrapper, 'video.bit_depth', SelectButton).emit(8)
    await flushPromises()
    expect(editor.job?.video).toMatchObject({ bit_depth: 8, profile: null })
    expect(labels()).toEqual(['Main (default)', 'Main'])
  })

  it('refuses 10-bit when the encoder failed its 10-bit test, and says why', async () => {
    const caps = withStatus(snapshot(), 'hevc_amf', {
      supports_10bit: false,
      reason_10bit: '10-bit is not supported by this GPU',
    })
    const { wrapper } = await mountTab({
      caps,
      job: jobWith({
        encoder: 'hevc_amf',
        preset: null,
        custom_params: '',
        bit_depth: 8,
        profile: null,
      }),
    })
    const options = control(wrapper, 'video.bit_depth', SelectButton).prop('options') as {
      value: number
      disabled: boolean
    }[]
    expect(options.find((option) => option.value === 10)?.disabled).toBe(true)
    expect(wrapper.find('[data-note="ten-bit"]').text()).toBe('10-bit is not supported by this GPU')
  })

  it('sets a fixed frame rate as a fraction, and same as source as none', async () => {
    const { wrapper, editor } = await mountTab()
    const rate = () => control(wrapper, 'video.framerate', Select)
    rate().emit('24000/1001')
    await flushPromises()
    expect(editor.job?.video?.framerate).toEqual({ num: 24000, den: 1001 })
    rate().emit((rate().prop('options') as { value: string }[])[0]?.value)
    await flushPromises()
    expect(editor.job?.video?.framerate).toBeNull()
  })

  it('shows a frame rate of the job that the list does not have', async () => {
    const { wrapper } = await mountTab({ job: jobWith({ framerate: { num: 18, den: 1 } }) })
    const options = control(wrapper, 'video.framerate', Select).prop('options') as {
      label: string
    }[]
    expect(options.at(-1)?.label).toBe('18')
  })

  it("names the frame rates in the app's locale", async () => {
    const { wrapper } = await mountTab({ job: jobWith({ framerate: { num: 2997, den: 125 } }) })
    const labels = () =>
      (control(wrapper, 'video.framerate', Select).prop('options') as { label: string }[]).map(
        (option) => option.label,
      )
    expect(labels()).toEqual(expect.arrayContaining(['23.976', '29.97', '59.94', '119.88', '25']))
    expect(labels().at(-1)).toBe('23.976')
    ;(wrapper.vm.$i18n as unknown as { locale: string }).locale = 'de'
    await flushPromises()
    expect(labels()).toEqual(expect.arrayContaining(['23,976', '29,97', '59,94', '119,88']))
  })

  it('makes one undo step of a speed preset drag', async () => {
    const { wrapper, editor } = await mountTab()
    const slider = wrapper.findComponent(SpeedPresetSlider)
    slider.vm.$emit('update:modelValue', 'slower')
    slider.vm.$emit('update:modelValue', 'veryslow')
    slider.vm.$emit('commit')
    expect(editor.job?.video?.preset).toBe('veryslow')
    editor.undo()
    expect(editor.job?.video?.preset).toBe('slow')
  })
})
