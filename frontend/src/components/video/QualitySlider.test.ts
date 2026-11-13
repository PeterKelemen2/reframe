import InputNumber from 'primevue/inputnumber'
import Slider from 'primevue/slider'
import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { mountShell } from '@/components/shell/testing'

import type { QualityBand, QualityMode } from './encoders'
import QualitySlider from './QualitySlider.vue'
import { encoderDefs, setUpVideo } from './testing'

const RF = encoderDefs().libx265?.rate_control?.quality as QualityMode
const BAND_1080: QualityBand = { max_height: 1080, low: 20, high: 24 }

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountSlider(
  props: { mode?: QualityMode; modelValue?: number; band?: QualityBand | null } = {},
) {
  const { wrapper } = await mountShell(QualitySlider, {
    pinia: setUpVideo().pinia,
    props: { mode: RF, modelValue: 22, band: BAND_1080, lines: 1080, ...props },
  })
  mounted.push(wrapper)
  return wrapper
}

describe('QualitySlider', () => {
  it("shades the band where its values are on the encoder's scale", async () => {
    const wrapper = await mountSlider()
    const band = wrapper.find('[data-band]').element as HTMLElement
    expect(Number.parseFloat(band.style.left)).toBeCloseTo((20 / 51) * 100, 3)
    expect(Number.parseFloat(band.style.width)).toBeCloseTo((4 / 51) * 100, 3)
    expect(wrapper.find('[data-band-note]').text()).toBe(
      'Recommended for 1080 lines: RF 20.0 to 24.0',
    )
  })

  it('says when the value is outside the band', async () => {
    const wrapper = await mountSlider({ modelValue: 30 })
    expect(wrapper.find('[data-band-note]').text()).toContain('The value is outside this range.')
  })

  it('shades nothing without a band', async () => {
    const wrapper = await mountSlider({ band: null })
    expect(wrapper.find('[data-band]').exists()).toBe(false)
    expect(wrapper.find('[data-band-note]').exists()).toBe(false)
  })

  it('sends each step of a drag on the scale, and the end of the drag', async () => {
    const wrapper = await mountSlider()
    const slider = wrapper.findComponent(Slider)
    slider.vm.$emit('update:modelValue', 22.04)
    slider.vm.$emit('update:modelValue', 23.37)
    slider.vm.$emit('slideend', {})
    expect(wrapper.emitted('update:modelValue')).toEqual([[23.4]])
    expect(wrapper.emitted('commit')).toHaveLength(1)
  })

  it('ends the step when a key is let go', async () => {
    const wrapper = await mountSlider()
    await wrapper.find('.quality-slider__track').trigger('keyup', { key: 'ArrowRight' })
    expect(wrapper.emitted('commit')).toHaveLength(1)
  })

  it.each([
    ['ArrowRight', 22.5],
    ['ArrowUp', 22.5],
    ['ArrowLeft', 21.5],
    ['ArrowDown', 21.5],
    ['PageUp', 27],
    ['PageDown', 17],
    ['Home', 0],
    ['End', 51],
  ])('moves a fine scale by half a unit, five a page, with %s', async (key, expected) => {
    const wrapper = await mountSlider()
    await wrapper.find('[role="slider"]').trigger('keydown', { key })
    expect(wrapper.emitted('update:modelValue')).toEqual([[expected]])
  })

  it('moves a whole-number scale by its step, and a 0–255 scale 25 a page', async () => {
    const cq = { ...RF, min: 1, max: 51, step: 1 }
    const whole = await mountSlider({ mode: cq })
    await whole.find('[role="slider"]').trigger('keydown', { key: 'ArrowRight' })
    await whole.find('[role="slider"]').trigger('keydown', { key: 'PageDown' })
    expect(whole.emitted('update:modelValue')).toEqual([[23], [17]])

    const qIndex = { ...RF, min: 1, max: 255, step: 1 }
    const wide = await mountSlider({ mode: qIndex, modelValue: 110 })
    await wide.find('[role="slider"]').trigger('keydown', { key: 'PageUp' })
    await wide.find('[role="slider"]').trigger('keydown', { key: 'ArrowLeft' })
    expect(wide.emitted('update:modelValue')).toEqual([[135], [109]])
  })

  it('keeps a typed value between the key steps', async () => {
    const wrapper = await mountSlider()
    wrapper.findComponent(InputNumber).vm.$emit('update:modelValue', 19.3)
    expect(wrapper.emitted('update:modelValue')).toEqual([[19.3]])
  })

  it('takes a typed value, on the scale, as a step of its own', async () => {
    const wrapper = await mountSlider()
    wrapper.findComponent(InputNumber).vm.$emit('update:modelValue', 60)
    expect(wrapper.emitted('update:modelValue')).toEqual([[51]])
    expect(wrapper.emitted('commit')).toHaveLength(1)
  })

  it("writes every number in the app's locale, not the browser's", async () => {
    const wrapper = await mountSlider()
    const i18n = wrapper.vm.$i18n as unknown as { locale: string }
    i18n.locale = 'de'
    await flushPromises()
    expect(wrapper.find('[role="slider"]').attributes('aria-valuetext')).toBe('RF 22,0')
    expect(wrapper.find('[data-band-note]').text()).toBe(
      'Recommended for 1080 lines: RF 20,0 to 24,0',
    )
  })
})
