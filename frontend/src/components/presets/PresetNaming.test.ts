import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, type PropType } from 'vue'

import { configureClient } from '@/api/client'
import { FakeServer, problem } from '@/api/testing/fakes'
import type { AppSettings, NamingOptions, Preset } from '@/api/types'
import { namingOptions, stubDom } from '@/components/naming/testing/samples'
import { mountShell } from '@/components/shell/testing'
import { usePresetsStore } from '@/stores/presets'
import { useSettingsStore } from '@/stores/settings'

import { NAMING_SAVE_DELAY } from './format'
import PresetNaming from './PresetNaming.vue'
import { preset, userPreset } from './testing'

// The naming editor is the naming task's; here it only has to show a value and emit a new one.
vi.mock('@/components/naming/NamingOptionsEditor.vue', () => ({
  default: defineComponent({
    props: {
      modelValue: { type: Object as PropType<NamingOptions>, required: true },
      disabled: Boolean,
    },
    emits: ['update:modelValue'],
    setup(props, { emit }) {
      return () =>
        h('input', {
          class: 'naming-stub',
          value: props.modelValue.movie_template,
          disabled: props.disabled,
          onInput: (event: Event) =>
            emit('update:modelValue', {
              ...props.modelValue,
              movie_template: (event.target as HTMLInputElement).value,
            }),
        })
    },
  }),
}))

const SETTINGS_NAMING = namingOptions({ movie_template: '{title} ({year})' })
const H265 = preset('h265-mkv-1080p', 'H.265 MKV 1080p')

let server: FakeServer
const mounted: { unmount(): void }[] = []

beforeAll(stubDom)

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  server = new FakeServer()
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  server.on('PUT /api/presets/u1', (request) => request.body)
  server.on('PUT /api/presets/u2', (request) => request.body)
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.useRealTimers()
})

async function mountNaming(shown: Preset, others: Preset[] = []) {
  const result = await mountShell(PresetNaming, {
    props: { preset: shown },
    setup: () => {
      usePresetsStore().presets = [H265, shown, ...others]
      useSettingsStore().settings = { output: { naming: SETTINGS_NAMING } } as AppSettings
    },
  })
  mounted.push(result.wrapper)
  return result.wrapper
}

function puts(): unknown[] {
  return server.requests.filter((request) => request.method === 'PUT').map((r) => r.body)
}

async function type(wrapper: Awaited<ReturnType<typeof mountNaming>>, value: string) {
  await wrapper.find('.naming-stub').setValue(value)
}

describe('the naming of a preset', () => {
  it('uses Settings → Output while it has none, shown read-only', async () => {
    const wrapper = await mountNaming(userPreset('u1', 'Mine', { naming: null }))
    expect(wrapper.find<HTMLInputElement>('.preset-naming__switch input').element.checked).toBe(
      true,
    )
    expect(wrapper.find<HTMLInputElement>('.naming-stub').element.value).toBe('{title} ({year})')
    expect(wrapper.find('.naming-stub').attributes('disabled')).toBeDefined()
  })

  it('gets its own naming, a copy of Settings → Output, saved at once when inherit is turned off', async () => {
    const wrapper = await mountNaming(userPreset('u1', 'Mine', { naming: null }))
    await wrapper.find('.preset-naming__switch input').setValue(false)
    await flushPromises()
    expect(puts()).toEqual([expect.objectContaining({ id: 'u1', naming: SETTINGS_NAMING })])
    expect(wrapper.find('.naming-stub').attributes('disabled')).toBeUndefined()
  })

  it('goes back to Settings → Output with inherit turned on', async () => {
    const wrapper = await mountNaming(userPreset('u1', 'Mine', { naming: namingOptions() }))
    await wrapper.find('.preset-naming__switch input').setValue(true)
    await flushPromises()
    expect(puts()).toEqual([expect.objectContaining({ id: 'u1', naming: null })])
  })

  it('saves edits once, after a pause, with the last value', async () => {
    const wrapper = await mountNaming(userPreset('u1', 'Mine', { naming: namingOptions() }))
    await type(wrapper, '{t')
    await type(wrapper, '{ti')
    await vi.advanceTimersByTimeAsync(NAMING_SAVE_DELAY - 100)
    await type(wrapper, '{title}')
    await vi.advanceTimersByTimeAsync(NAMING_SAVE_DELAY - 100)
    expect(puts()).toEqual([])
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(puts()).toEqual([
      expect.objectContaining({
        id: 'u1',
        naming: expect.objectContaining({ movie_template: '{title}' }),
      }),
    ])
  })

  it('saves an edit that waits into its own preset when another preset is shown', async () => {
    const other = userPreset('u2', 'Other', { naming: namingOptions({ movie_template: 'other' }) })
    const wrapper = await mountNaming(userPreset('u1', 'Mine', { naming: namingOptions() }), [
      other,
    ])
    await type(wrapper, '{title}')
    await wrapper.setProps({ preset: other })
    await flushPromises()
    expect(puts()).toEqual([
      expect.objectContaining({
        id: 'u1',
        naming: expect.objectContaining({ movie_template: '{title}' }),
      }),
    ])
    expect(wrapper.find<HTMLInputElement>('.naming-stub').element.value).toBe('other')
  })

  it('saves an edit that waits when it closes', async () => {
    const wrapper = await mountNaming(userPreset('u1', 'Mine', { naming: namingOptions() }))
    await type(wrapper, '{title}')
    wrapper.unmount()
    mounted.length = 0
    await flushPromises()
    expect(puts()).toHaveLength(1)
  })

  it('keeps a built-in preset’s naming read-only', async () => {
    const wrapper = await mountNaming(preset('fast', 'Fast', { naming: null }))
    expect(wrapper.find('.preset-naming__switch input').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.naming-stub').attributes('disabled')).toBeDefined()
  })

  it('says why a save was refused', async () => {
    server.on('PUT /api/presets/u1', () =>
      problem(403, 'path.outside_roots', 'The folder is outside the output roots'),
    )
    const wrapper = await mountNaming(userPreset('u1', 'Mine', { naming: namingOptions() }))
    await type(wrapper, '{title}')
    await vi.advanceTimersByTimeAsync(NAMING_SAVE_DELAY)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toBe('The folder is outside the output roots')
  })
})
