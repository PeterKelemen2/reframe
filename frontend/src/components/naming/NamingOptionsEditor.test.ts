import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { deferred, FakeServer, type Recorded } from '@/api/testing/fakes'
import type { NameResult, NamingOptions } from '@/api/types'
import { mountBase } from '@/components/base/testing'
import { platform } from '@/platform'
import { useSystemStore } from '@/stores/system'
import { useToastStore } from '@/stores/toasts'

import NamingOptionsEditor from './NamingOptionsEditor.vue'
import { PREVIEW_DEBOUNCE } from './preview'
import {
  hacksawResult,
  namingOptions,
  stubDom,
  unknownVariable,
  VARIABLES,
} from './testing/samples'

vi.mock('@/platform', () => ({
  platform: { pickFolder: vi.fn<(opts?: { title?: string }) => Promise<string | null>>() },
}))

stubDom()

const ROUTE = 'POST /api/naming/preview'

interface PreviewBody {
  naming: NamingOptions
  source_ids: string[]
  container: string
}

let server: FakeServer

function bodies(): PreviewBody[] {
  return server.requests
    .filter((request: Recorded) => `${request.method} ${request.path}` === ROUTE)
    .map((request) => request.body as PreviewBody)
}

function mountEditor(props: Record<string, unknown> = {}, model = namingOptions()) {
  const wrapper = mountBase(NamingOptionsEditor, {
    props: {
      modelValue: model,
      sourceIds: ['a'],
      'onUpdate:modelValue': (next: NamingOptions) => wrapper.setProps({ modelValue: next }),
      ...props,
    },
  })
  useSystemStore().namingVariables = VARIABLES
  return wrapper
}

async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE)
  await flushPromises()
}

beforeEach(() => {
  vi.useFakeTimers()
  server = new FakeServer().on(ROUTE, (request) =>
    (request.body as PreviewBody).source_ids.map(() => hacksawResult()),
  )
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  vi.useRealTimers()
  vi.mocked(platform.pickFolder).mockReset()
  document.body.innerHTML = ''
})

describe('NamingOptionsEditor', () => {
  it('names the word-separator list by its label', () => {
    const wrapper = mountEditor()
    const combobox = wrapper.get('[data-option="word_separator"] [role="combobox"]')
    const label = document.getElementById(combobox.attributes('aria-labelledby') ?? '')
    expect(label?.textContent).toBe('Word separator')
  })

  it('emits a new object for a change and leaves the given one as it was', async () => {
    const given = Object.freeze(namingOptions())
    const wrapper = mountEditor({ 'onUpdate:modelValue': undefined }, given)
    await wrapper.get('[data-option="title_case"] input').setValue(true)
    const emitted = wrapper.emitted('update:modelValue')?.at(-1)?.[0] as NamingOptions
    expect(emitted).toEqual({ ...given, title_case: true })
    expect(emitted).not.toBe(given)
    expect(given.title_case).toBe(false)
  })

  it('previews every source with the options and the container, once per pause in the edits', async () => {
    // A movie and an episode: each template is checked by the source that uses it.
    server.on(ROUTE, () => [hacksawResult(), hacksawResult({ template_kind: 'episode' })])
    const wrapper = mountEditor({ sourceIds: ['a', 'b'], container: 'mp4' })
    await settle()
    expect(bodies()).toHaveLength(1)

    const input = wrapper.get('[data-template="movie"] input')
    await input.setValue('{name}')
    await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE - 50)
    await input.setValue('{name}.{year}')
    await vi.advanceTimersByTimeAsync(PREVIEW_DEBOUNCE - 50)
    expect(bodies()).toHaveLength(1)
    await settle()

    expect(bodies()).toHaveLength(2)
    expect(bodies()[1]).toEqual({
      naming: namingOptions({ movie_template: '{name}.{year}' }),
      source_ids: ['a', 'b'],
      container: 'mp4',
    })
    expect(wrapper.findAll('[data-testid="naming-result"]')).toHaveLength(2)
  })

  it('never shows an older answer over a newer one', async () => {
    const slow = deferred<NameResult[]>()
    let calls = 0
    server.on(ROUTE, () => {
      calls += 1
      return calls === 2 ? slow.promise : [hacksawResult({ relative_path: `answer-${calls}.mkv` })]
    })
    const wrapper = mountEditor()
    await settle()
    await wrapper.get('[data-template="movie"] input').setValue('{name}')
    await settle()
    await wrapper.get('[data-template="movie"] input').setValue('{name}.x')
    await settle()
    slow.resolve([hacksawResult({ relative_path: 'answer-2.mkv' })])
    await flushPromises()

    expect(wrapper.get('[data-testid="naming-result"]').text()).toBe('answer-3.mkv')
  })

  it('shows the issues of the template a source used at that template, and checks the other one on its own', async () => {
    server.on(ROUTE, (request) => {
      const { naming } = request.body as PreviewBody
      const issues = naming.movie_template.includes('titel') ? [unknownVariable()] : []
      return [hacksawResult({ template: naming.movie_template, issues })]
    })
    const wrapper = mountEditor(
      {},
      namingOptions({ movie_template: '{main_title}', episode_template: '{main_titel}' }),
    )
    await settle()

    expect(wrapper.get('[data-path="naming.movie_template"]').text()).not.toContain('Unknown')
    expect(wrapper.get('[data-path="naming.episode_template"]').text()).toContain(
      'Unknown variable {main_titel}',
    )
    expect(bodies()[1]).toMatchObject({
      naming: { movie_template: '{main_titel}', episode_template: '{main_titel}' },
      source_ids: ['a'],
    })
  })

  it("puts a template issue's fix into its field", async () => {
    server.on(ROUTE, () => [hacksawResult({ issues: [unknownVariable()] })])
    const wrapper = mountEditor({}, namingOptions({ movie_template: '{main_titel}' }))
    await settle()
    const fix = wrapper
      .get('[data-path="naming.movie_template"]')
      .findAll('button')
      .find((button) => button.text() === 'Use {main_title}')
    await fix?.trigger('click')
    expect(wrapper.props('modelValue').movie_template).toBe('{main_title}')
  })

  it('asks for no preview without sources and says why', async () => {
    const wrapper = mountEditor({ sourceIds: [] })
    await settle()
    expect(bodies()).toHaveLength(0)
    expect(wrapper.text()).toContain('Open a source file to see the names it gets.')
  })

  it('shows why the preview failed', async () => {
    server.on(ROUTE, () => new Response('{}', { status: 500 }))
    const wrapper = mountEditor()
    await settle()
    expect(wrapper.get('[role="alert"]').text()).toMatch(/^No preview: /)
  })

  it("inserts a chip's variable into the template field that had the focus last", async () => {
    const wrapper = mountEditor()
    await settle()
    await wrapper.get('[data-template="episode"] input').trigger('focus')
    await wrapper.get('[data-variable="year"]').trigger('click')
    await flushPromises()
    expect(wrapper.props('modelValue')).toMatchObject({
      movie_template: '{main_title}',
      episode_template: '{main_title}{year}',
    })
  })

  it('sets the folder that was picked', async () => {
    vi.mocked(platform.pickFolder).mockResolvedValue('/picked')
    const wrapper = mountEditor()
    await wrapper.get('[data-action="browse"]').trigger('click')
    await flushPromises()
    expect(wrapper.props('modelValue').output_folder).toBe('/picked')
  })

  it('says so when no folder can be picked, and keeps the folder', async () => {
    vi.mocked(platform.pickFolder).mockRejectedValue(new Error('not available'))
    const wrapper = mountEditor()
    await wrapper.get('[data-action="browse"]').trigger('click')
    await flushPromises()
    expect(useToastStore().items.map((toast) => toast.summary)).toEqual([
      'A folder cannot be chosen here: type its path.',
    ])
    expect(wrapper.props('modelValue').output_folder).toBe('/output')
  })
})
