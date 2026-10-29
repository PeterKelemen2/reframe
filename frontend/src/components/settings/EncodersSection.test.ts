import { flushPromises, type VueWrapper } from '@vue/test-utils'
import Select from 'primevue/select'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { deferred } from '@/api/testing/fakes'
import type { CapabilitySnapshot, Definitions, EncoderStatus } from '@/api/types'
import { useSystemStore } from '@/stores/system'

import EncodersSection from './EncodersSection.vue'
import { mountSettings, refusal } from './testing'

// jsdom has none; PrimeVue's Select listens to the orientation with one.
globalThis.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }) as unknown as MediaQueryList

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

const definitions = {
  video_encoders: {
    hevc_nvenc: { id: 'hevc_nvenc', label: 'NVIDIA NVENC H.265', family: 'nvenc' },
    hevc_vaapi: { id: 'hevc_vaapi', label: 'VAAPI H.265', family: 'vaapi' },
  },
  audio_encoders: { aac: { id: 'aac', label: 'AAC' } },
} as unknown as Definitions

function status(id: string, extra: Partial<EncoderStatus> = {}): EncoderStatus {
  return { id, state: 'available', hardware: true, in_build: true, ...extra } as EncoderStatus
}

function capabilities(): CapabilitySnapshot {
  return {
    encoders: {
      hevc_nvenc: status('hevc_nvenc', {
        state: 'unavailable',
        reason: 'NVIDIA driver not found',
        checked_at: '2026-10-29T20:46:18Z',
      }),
      hevc_vaapi: status('hevc_vaapi', { device: '/dev/dri/renderD128' }),
      aac: status('aac', { hardware: false }),
    },
    detecting: false,
    from_cache: false,
    checked_at: '2026-10-29T20:46:18Z',
  } as CapabilitySnapshot
}

async function mountEncoders() {
  const result = await mountSettings(EncodersSection, {
    setup: () => {
      const system = useSystemStore()
      system.definitions = definitions
      system.capabilities = capabilities()
    },
  })
  mounted.push(result.wrapper)
  const select = () =>
    result.wrapper
      .findAllComponents(Select)
      .find((component) => component.attributes('data-field') === 'vaapi-device')
  return { ...result, system: useSystemStore(), select }
}

describe('the Encoders section', () => {
  it('shows every encoder with its status, reason and last check', async () => {
    const { wrapper } = await mountEncoders()
    const row = (id: string) => wrapper.find(`[data-encoder="${id}"]`)
    expect(row('hevc_nvenc').text()).toContain('NVIDIA NVENC H.265')
    expect(row('hevc_nvenc').find('[data-field="status"]').text()).toBe(
      'Unavailable: NVIDIA driver not found',
    )
    expect(row('hevc_nvenc').find('[data-field="checked"]').text()).toMatch(/\d/)
    expect(row('aac').find('[data-field="checked"]').text()).toBe('Not checked')
    expect(row('aac').text()).toContain('Audio')
    expect(row('hevc_vaapi').text()).toContain('on /dev/dri/renderD128')
    expect(wrapper.find('[data-field="last-check"]').text()).toMatch(/^Last full check: .*\d/)
  })

  it('re-scans and stays busy until the detection task has ended', async () => {
    const { wrapper, system } = await mountEncoders()
    const done = deferred()
    system.rescanEncoders = vi.fn<() => Promise<void>>(() => done.promise)
    await wrapper.find('[data-action="rescan"]').trigger('click')
    await flushPromises()
    expect(system.rescanEncoders).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-action="rescan"]').attributes('disabled')).toBeDefined()
    done.resolve()
    await flushPromises()
    expect(wrapper.find('[data-action="rescan"]').attributes('disabled')).toBeUndefined()
  })

  it('turns hardware test encodes off at once', async () => {
    const { wrapper, server } = await mountEncoders()
    await wrapper.find('[data-field="hardware-tests"] input').trigger('change')
    await flushPromises()
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/encoders/hardware_tests', value: false }],
    ])
  })

  it('offers automatic, each node an encoder works on, and another node', async () => {
    const { select } = await mountEncoders()
    const options = ((select()?.props('options') ?? []) as { value: string }[]).map(
      (option) => option.value,
    )
    expect(options).toEqual(['auto', '/dev/dri/renderD128', 'other'])
    expect(select()?.props('modelValue')).toBe('auto')
  })

  it('saves a chosen node, and automatic as no node', async () => {
    const { select, server } = await mountEncoders()
    select()?.vm.$emit('update:modelValue', '/dev/dri/renderD128')
    await flushPromises()
    expect(select()?.props('modelValue')).toBe('/dev/dri/renderD128')
    select()?.vm.$emit('update:modelValue', 'auto')
    await flushPromises()
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/encoders/vaapi_device', value: '/dev/dri/renderD128' }],
      [{ op: 'replace', path: '/encoders/vaapi_device', value: null }],
    ])
  })

  it('saves a typed node; a refused one stays in the field with the reason', async () => {
    const { wrapper, select, server } = await mountEncoders()
    select()?.vm.$emit('update:modelValue', 'other')
    await flushPromises()
    expect(server.patches).toEqual([])
    server.refuse = () =>
      refusal(403, 'settings.vaapi_device_forbidden', 'Only a render node', 'Name one.')
    await wrapper.find('[data-field="vaapi-node"]').setValue('/dev/dri/card1')
    await wrapper.find('[data-action="use-node"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.rf-field__issue').text()).toContain('Only a render node. Name one.')
    expect((wrapper.find('[data-field="vaapi-node"]').element as HTMLInputElement).value).toBe(
      '/dev/dri/card1',
    )

    server.refuse = () => undefined
    await wrapper.find('[data-field="vaapi-node"]').setValue('/dev/dri/renderD129')
    await wrapper.find('[data-field="vaapi-node"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(server.document.encoders?.vaapi_device).toBe('/dev/dri/renderD129')
    expect(wrapper.find('[data-field="vaapi-node"]').exists()).toBe(false)
    expect(wrapper.find('.rf-field__issue').exists()).toBe(false)
    expect(select()?.props('modelValue')).toBe('/dev/dri/renderD129')
  })
})
