import { flushPromises, type VueWrapper } from '@vue/test-utils'
import SelectButton from 'primevue/selectbutton'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import type { NamingOptions, Preset, SourceEntry } from '@/api/types'
import { samplePreset } from '@/editor/testing/samples'
import { usePresetsStore } from '@/stores/presets'
import { useSourcesStore } from '@/stores/sources'

import OutputSection from './OutputSection.vue'
import { defaultSettings, mountSettings, refusal } from './testing'
import { NAMING_SAVE_DELAY, namingOps } from './useNamingSetting'

// The naming editor has its own tests; here it only hands over whole objects.
vi.mock('@/components/naming/NamingOptionsEditor.vue', () => ({
  default: defineComponent({
    name: 'NamingOptionsEditor',
    props: ['modelValue', 'sourceIds', 'container', 'disabled'],
    emits: ['update:modelValue'],
    setup: () => () => h('div', { class: 'naming-stub' }),
  }),
}))

globalThis.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }) as unknown as MediaQueryList

const mounted: VueWrapper[] = []

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
})

afterEach(() => {
  vi.useRealTimers()
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

function naming(): NamingOptions {
  return defaultSettings().output?.naming as NamingOptions
}

async function mountOutput(setup?: () => void) {
  const result = await mountSettings(OutputSection, { setup })
  mounted.push(result.wrapper)
  const editor = () => result.wrapper.findComponent({ name: 'NamingOptionsEditor' })
  return { ...result, editor }
}

describe('namingOps', () => {
  it('replaces only the members that changed, and adds one the settings lack', () => {
    const saved = naming()
    delete saved.output_folder
    const next = { ...naming(), movie_template: '{title}', output_folder: '/media/x' }
    expect(namingOps(saved, next)).toEqual([
      { op: 'replace', path: '/output/naming/movie_template', value: '{title}' },
      { op: 'add', path: '/output/naming/output_folder', value: '/media/x' },
    ])
    expect(namingOps(naming(), naming())).toEqual([])
  })
})

describe('the Output section', () => {
  it('saves a run of naming edits once, after the pause, with the changed members only', async () => {
    const { editor, server } = await mountOutput()
    const type = async (template: string) => {
      editor().vm.$emit('update:modelValue', { ...naming(), movie_template: template })
      await flushPromises()
      vi.advanceTimersByTime(NAMING_SAVE_DELAY - 100)
    }
    await type('{main_title} (')
    await type('{main_title} ({')
    await type('{main_title} ({year})')
    expect(server.patches).toEqual([])
    expect(editor().props('modelValue').movie_template).toBe('{main_title} ({year})')
    vi.advanceTimersByTime(100)
    await flushPromises()
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/output/naming/movie_template', value: '{main_title} ({year})' }],
    ])
    expect(server.document.output?.naming?.movie_template).toBe('{main_title} ({year})')
  })

  it('keeps a refused folder shown with the server reason', async () => {
    const { wrapper, editor, server } = await mountOutput()
    server.refuse = () =>
      refusal(
        403,
        'path.outside_roots',
        'The path is outside the allowed folders',
        '/etc is not inside.',
      )
    editor().vm.$emit('update:modelValue', { ...naming(), output_folder: '/etc' })
    vi.advanceTimersByTime(NAMING_SAVE_DELAY)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain(
      'The path is outside the allowed folders. /etc is not inside.',
    )
    expect(editor().props('modelValue').output_folder).toBe('/etc')
    expect(server.document.output?.naming?.output_folder).toBe('/media/out')

    server.refuse = () => undefined
    editor().vm.$emit('update:modelValue', { ...naming(), output_folder: '/media/out/films' })
    vi.advanceTimersByTime(NAMING_SAVE_DELAY)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(server.document.output?.naming?.output_folder).toBe('/media/out/films')
  })

  it('saves a waiting edit when the page is left', async () => {
    const { wrapper, editor, server } = await mountOutput()
    editor().vm.$emit('update:modelValue', { ...naming(), title_case: true })
    await flushPromises()
    wrapper.unmount()
    mounted.splice(0)
    await flushPromises()
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/output/naming/title_case', value: true }],
    ])
  })

  it('gives the editor the open sources that can be named', async () => {
    const { editor } = await mountOutput(() => {
      useSourcesStore().entries = [
        { id: 'a', path: '/media/a.mkv', source: {} },
        { id: 'b', path: '/media/b.mkv', source: null },
      ] as SourceEntry[]
    })
    expect(editor().props('sourceIds')).toEqual(['a'])
  })

  it('previews the names with the default preset’s container', async () => {
    const preset = samplePreset()
    const mp4 = { ...preset, id: 'mine', output: { ...preset.output, container: 'mp4' } }
    const { editor } = await mountOutput(() => {
      const presets = usePresetsStore()
      presets.presets = [preset, mp4 as Preset]
      presets.defaultId = 'mine'
      presets.loaded = true
    })
    expect(editor().props('container')).toBe('mp4')
    usePresetsStore().defaultId = preset.id
    await flushPromises()
    expect(editor().props('container')).toBe(preset.output?.container)
  })

  it('reads the presets for the preview, and names with Matroska without them', async () => {
    const { editor, server } = await mountOutput()
    expect(server.count('GET /api/presets')).toBe(1)
    expect(editor().props('container')).toBe('mkv')
  })

  it('offers no default container: the preset decides', async () => {
    const { wrapper } = await mountOutput()
    expect(wrapper.find('[data-field="default-container"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Default container')
  })

  it('saves the collision and partial-file behaviour at once', async () => {
    const { wrapper, server } = await mountOutput()
    const buttons = wrapper.findAllComponents(SelectButton)
    buttons
      .find((c) => c.attributes('data-field') === 'collision')
      ?.vm.$emit('update:modelValue', 'ask')
    buttons
      .find((c) => c.attributes('data-field') === 'partial-file')
      ?.vm.$emit('update:modelValue', 'keep')
    await flushPromises()
    expect(server.patches).toEqual([
      [{ op: 'replace', path: '/output/collision', value: 'ask' }],
      [{ op: 'replace', path: '/output/partial_file', value: 'keep' }],
    ])
  })
})
