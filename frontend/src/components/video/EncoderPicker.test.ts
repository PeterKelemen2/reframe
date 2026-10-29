import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { mountShell } from '@/components/shell/testing'
import { useSystemStore } from '@/stores/system'

import EncoderPicker from './EncoderPicker.vue'
import { setUpVideo, snapshot, withStatus } from './testing'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountPicker(modelValue = 'libx265') {
  const { wrapper } = await mountShell(EncoderPicker, {
    pinia: setUpVideo().pinia,
    props: { modelValue },
  })
  mounted.push(wrapper)
  await wrapper.find('[role="combobox"]').trigger('click')
  await flushPromises()
  return wrapper
}

function option(id: string): HTMLElement {
  const entry = document.querySelector(`[data-encoder="${id}"]`)
  return entry?.closest('[role="option"]') as HTMLElement
}

describe('EncoderPicker', () => {
  it('groups the encoders by family, in order', async () => {
    await mountPicker()
    const groups = [...document.querySelectorAll('.p-select-option-group')].map((group) =>
      group.textContent?.trim(),
    )
    expect(groups).toEqual(['Software', 'NVIDIA NVENC', 'Intel QSV', 'AMD AMF', 'VAAPI'])
  })

  it('shows each status, and an unavailable encoder with its reason in its name', async () => {
    await mountPicker()
    expect(option('hevc_amf').textContent).toContain('Available')
    expect(option('hevc_nvenc').textContent).toContain('Unavailable: NVIDIA driver not found')
    expect(option('hevc_nvenc').getAttribute('aria-label')).toBe(
      'NVIDIA NVENC H.265 (hevc_nvenc), Unavailable: NVIDIA driver not found',
    )
    expect(option('hevc_nvenc').getAttribute('aria-disabled')).toBe('true')
    expect(option('hevc_amf').getAttribute('aria-disabled')).toBe('false')
  })

  it('shows checking… while detection runs', async () => {
    await mountPicker()
    const system = useSystemStore()
    system.capabilities = withStatus(snapshot({ detecting: true }), 'hevc_amf', {
      state: 'checking',
    })
    await flushPromises()
    expect(option('hevc_amf').textContent).toContain('Checking…')
    expect(option('hevc_amf').querySelector('[data-tone]')?.getAttribute('data-tone')).toBe('busy')
  })

  it('does not choose an unavailable encoder', async () => {
    const wrapper = await mountPicker()
    // jsdom has no `pointer-events: none`: PrimeVue's own guard is not there.
    option('hevc_nvenc').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    option('hevc_nvenc').click()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('chooses an available encoder', async () => {
    const wrapper = await mountPicker()
    option('hevc_amf').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    option('hevc_amf').click()
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')).toEqual([['hevc_amf']])
  })

  it('still shows an encoder the definitions do not have', async () => {
    const wrapper = await mountPicker('h266_future')
    expect(wrapper.find('.encoder-picker__value').text()).toContain('h266_future')
    expect(option('h266_future').textContent).toContain('Status not known')
  })
})
