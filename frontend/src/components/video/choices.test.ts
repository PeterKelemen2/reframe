import Select from 'primevue/select'
import Slider from 'primevue/slider'
import { afterEach, describe, expect, it } from 'vitest'

import { mountShell } from '@/components/shell/testing'

import ChoiceSelect from './ChoiceSelect.vue'
import type { ChoiceSetting } from './encoders'
import SpeedPresetSlider from './SpeedPresetSlider.vue'
import { encoderDefs, setUpVideo } from './testing'

const defs = encoderDefs()
const X265_PRESETS = defs.libx265?.presets as ChoiceSetting
const AMF_PRESETS = defs.hevc_amf?.presets as ChoiceSetting
const NVENC_TUNES = defs.hevc_nvenc?.tunes as ChoiceSetting

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mount<C>(component: C, props: Record<string, unknown>) {
  const { wrapper } = await mountShell(component as never, { pinia: setUpVideo().pinia, props })
  mounted.push(wrapper)
  return wrapper
}

describe('ChoiceSelect', () => {
  it("writes null for the encoder's default and the value for a choice", async () => {
    const wrapper = await mount(ChoiceSelect, {
      setting: NVENC_TUNES,
      modelValue: 'hq',
      noneLabel: 'High quality (default)',
    })
    const select = wrapper.findComponent(Select)
    const options = select.props('options') as { value: string; label: string }[]
    expect(options[0]?.label).toBe('High quality (default)')
    select.vm.$emit('update:modelValue', options[0]?.value)
    select.vm.$emit('update:modelValue', 'll')
    expect(wrapper.emitted('update:modelValue')).toEqual([[null], ['ll']])
  })

  it('keeps a value the encoder does not have, so that its issue has something to point at', async () => {
    const wrapper = await mount(ChoiceSelect, {
      setting: NVENC_TUNES,
      modelValue: 'film',
      noneLabel: 'None',
    })
    const options = wrapper.findComponent(Select).props('options') as { value: string }[]
    expect(options.at(-1)).toEqual({ value: 'film', label: 'film' })
  })
})

describe('SpeedPresetSlider', () => {
  it("shows the encoder's default where the job has none", async () => {
    const wrapper = await mount(SpeedPresetSlider, { setting: X265_PRESETS, modelValue: null })
    expect(wrapper.findComponent(Slider).props('modelValue')).toBe(5)
    expect(wrapper.find('[data-speed-value]').text()).toBe('Medium (default)')
    expect(wrapper.find('.speed-preset__reset').exists()).toBe(false)
  })

  it('names the default of an encoder that has none in the definitions', async () => {
    const wrapper = await mount(SpeedPresetSlider, { setting: AMF_PRESETS, modelValue: null })
    expect(wrapper.find('[data-speed-value]').text()).toBe("The encoder's default")
  })

  it('moves along the presets, fastest first, and back to the default', async () => {
    const wrapper = await mount(SpeedPresetSlider, { setting: X265_PRESETS, modelValue: 'slow' })
    expect(wrapper.findComponent(Slider).props('modelValue')).toBe(6)
    wrapper.findComponent(Slider).vm.$emit('update:modelValue', 0)
    wrapper.findComponent(Slider).vm.$emit('slideend', {})
    await wrapper.find('.speed-preset__reset').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([['ultrafast'], [null]])
    expect(wrapper.emitted('commit')).toHaveLength(2)
  })
})
