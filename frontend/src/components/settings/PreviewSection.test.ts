import { flushPromises, type VueWrapper } from '@vue/test-utils'
import InputNumber from 'primevue/inputnumber'
import { afterEach, describe, expect, it } from 'vitest'

import { configureClient } from '@/api/client'
import { mountShell } from '@/components/shell/testing'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import PreviewSection from './PreviewSection.vue'
import { defaultSettings, SettingsServer, systemInfo } from './testing'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

function withPreview() {
  return { ...defaultSettings(), preview: { sample_frames: 10, cache_size_mb: 1024 } }
}

async function mountPreview(options: { readOnly?: boolean } = {}) {
  const server = new SettingsServer()
  server.document = withPreview()
  let size = 3 * 1024 * 1024
  server.on('GET /api/preview/cache', () => ({ size }))
  server.on('DELETE /api/preview/cache', () => {
    const freed = size
    size = 0
    return { freed }
  })
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const { wrapper } = await mountShell(PreviewSection, {
    setup: () => {
      useSystemStore().info = systemInfo({ settings_read_only: options.readOnly === true })
      useSettingsStore().settings = withPreview()
      useSettingsStore().loaded = true
    },
  })
  mounted.push(wrapper)
  const input = (field: string) =>
    wrapper.findAllComponents(InputNumber).find((c) => c.attributes('data-field') === field)!
  return { wrapper, server, input }
}

describe('the Preview section', () => {
  it('saves the number of sample frames and the cache size limit', async () => {
    const { input, server } = await mountPreview()
    input('sample-frames').vm.$emit('update:modelValue', 5)
    input('cache-limit').vm.$emit('update:modelValue', 256)
    await flushPromises()
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/preview/sample_frames', value: 5 }],
      [{ op: 'replace', path: '/preview/cache_size_mb', value: 256 }],
    ])
    expect(useSettingsStore().settings?.preview).toEqual({ sample_frames: 5, cache_size_mb: 256 })
  })

  it('keeps the saved number when a field is emptied', async () => {
    const { input, server } = await mountPreview()
    input('sample-frames').vm.$emit('update:modelValue', null)
    await flushPromises()
    expect(server.patches).toEqual([])
  })

  it('shows a refused count at its field', async () => {
    const { input, server, wrapper } = await mountPreview()
    server.refuse = () =>
      new Response(
        JSON.stringify({
          type: 'about:blank',
          title: 'Not valid',
          status: 422,
          code: 'settings.invalid',
          issues: [
            {
              severity: 'error',
              code: 'settings.invalid',
              path: 'preview.sample_frames',
              message: 'Input should be less than or equal to 60',
              fixes: [],
            },
          ],
        }),
        { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
      )
    input('sample-frames').vm.$emit('update:modelValue', 99)
    await flushPromises()
    expect(wrapper.find('.rf-field__issue').text()).toContain('less than or equal to 60')
    expect(input('sample-frames').props('modelValue')).toBe(99)
  })

  it('cannot change the settings while they are read-only', async () => {
    const { input } = await mountPreview({ readOnly: true })
    expect(input('sample-frames').props('disabled')).toBe(true)
    expect(input('cache-limit').props('disabled')).toBe(true)
  })

  it('shows the cache size, and what Clear cache freed', async () => {
    const { wrapper, server } = await mountPreview()
    expect(wrapper.find('[data-field="cache-size"]').text()).toBe('The cache holds 3.0 MiB.')
    await wrapper.find('[data-action="clear-cache"]').trigger('click')
    await flushPromises()
    expect(server.count('DELETE /api/preview/cache')).toBe(1)
    expect(wrapper.find('[data-field="freed"]').text()).toBe('Cleared: 3.0 MiB freed.')
    expect(wrapper.find('[data-field="cache-size"]').text()).toBe('The cache holds 0 B.')
  })
})
