import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { deferred, FakeServer } from '@/api/testing/fakes'
import type { Definitions, NameResult } from '@/api/types'
import { mountBase } from '@/components/base/testing'
import { hacksawResult, stubDom } from '@/components/naming/testing/samples'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { templateOfPreset } from '@/stores/presets'
import { useSystemStore } from '@/stores/system'

import OutputCard from './OutputCard.vue'
import { sampleDefinitions } from './testing'

// It previews the job on its own; here only the container and the path matter.
vi.mock('@/components/naming/JobNamingEditor.vue', () => ({
  // The Output card's options are in its slot.
  default: {
    name: 'JobNamingEditor',
    setup:
      (_props: unknown, { slots }: { slots: { default?: () => unknown } }) =>
      () =>
        slots.default?.(),
  },
}))

stubDom()

const PREVIEW = 'POST /api/naming/preview'

function definitions(): Definitions {
  const base = sampleDefinitions()
  const extensions = { mkv: ['.mkv'], mp4: ['.mp4', '.m4v'], webm: ['.webm'] } as const
  for (const [id, list] of Object.entries(extensions)) {
    const container = base.containers?.[id as keyof typeof extensions]
    if (container) container.extensions = [...list]
  }
  return base
}

let server: FakeServer
let extension: () => Promise<string> | string
const mounted: VueWrapper[] = []

beforeEach(() => {
  extension = () => 'mp4'
  server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(sampleJob()))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
    .on(PREVIEW, async (): Promise<NameResult[]> => [
      hacksawResult({ extension: await extension() }),
    ])
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountCard() {
  const wrapper = mountBase(OutputCard)
  mounted.push(wrapper)
  useSystemStore().definitions = definitions()
  const editor = useEditorStore()
  await editor.open('src')
  await flushPromises()
  return { wrapper, editor }
}

async function choose(wrapper: VueWrapper, label: string): Promise<void> {
  const button = wrapper.findAll('[data-field="container"] button').find((b) => b.text() === label)
  await button!.trigger('click')
}

it('leaves the name, the folder and the name source to the naming editor', async () => {
  const { wrapper } = await mountCard()
  expect(wrapper.findComponent({ name: 'JobNamingEditor' }).exists()).toBe(true)
  expect(wrapper.text()).not.toContain('multitrack.mkv')
  expect(wrapper.text()).not.toContain('/output')
})

describe('the Output card’s container', () => {
  it('changes the path’s extension with the container, in one undo step', async () => {
    const { wrapper, editor } = await mountCard()
    await choose(wrapper, 'MP4')
    expect(editor.job?.output?.container).toBe('mp4')
    expect(editor.job?.output?.path).toBe('/output/multitrack.mp4')
    await flushPromises()
    expect(editor.job?.output?.path).toBe('/output/multitrack.mp4')

    editor.undo()
    expect(editor.job?.output?.container).toBe('mkv')
    expect(editor.job?.output?.path).toBe('/output/multitrack.mkv')
  })

  it('takes the extension the naming gives (.m4v) into the same undo step; an add waits for it', async () => {
    extension = () => 'm4v'
    const { wrapper, editor } = await mountCard()
    await choose(wrapper, 'MP4')
    expect(editor.editing).toBe(true)
    await flushPromises()
    expect(editor.job?.output?.path).toBe('/output/multitrack.m4v')
    expect(editor.editing).toBe(false)
    expect(server.count(PREVIEW)).toBe(1)

    editor.undo()
    expect(editor.job?.output?.container).toBe('mkv')
    expect(editor.job?.output?.path).toBe('/output/multitrack.mkv')
  })

  it('does not write the naming’s extension over an undo made before it came', async () => {
    const answer = deferred<string>()
    extension = () => answer.promise
    const { wrapper, editor } = await mountCard()
    await choose(wrapper, 'MP4')
    editor.undo()
    answer.resolve('m4v')
    await flushPromises()
    expect(editor.job?.output?.container).toBe('mkv')
    expect(editor.job?.output?.path).toBe('/output/multitrack.mkv')
    expect(editor.canRedo).toBe(true)
    expect(editor.editing).toBe(false)
  })

  it('keeps the container’s first extension when the naming cannot be asked', async () => {
    server.on(PREVIEW, () => new Response('{}', { status: 500 }))
    const { wrapper, editor } = await mountCard()
    await choose(wrapper, 'MP4')
    await flushPromises()
    expect(editor.job?.output?.path).toBe('/output/multitrack.mp4')
    expect(editor.editing).toBe(false)
  })

  it('in a group changes only the container: the server names each file', async () => {
    const { wrapper, editor } = await mountCard()
    editor.target = {
      kind: 'group',
      groupId: 'g1',
      sourceId: 'src',
      job: editor.job!,
      template: templateOfPreset(samplePreset()),
      presetId: null,
      overrides: {},
      scope: 'group',
    }
    const patch = vi.spyOn(editor, 'patch').mockImplementation(() => undefined)
    await choose(wrapper, 'MP4')
    await flushPromises()
    expect(patch.mock.calls).toEqual([[[{ op: 'add', path: '/output/container', value: 'mp4' }]]])
    expect(server.count(PREVIEW)).toBe(0)
  })

  it('asks nothing for a container with one extension', async () => {
    const { wrapper, editor } = await mountCard()
    await choose(wrapper, 'WebM')
    expect(editor.job?.output?.path).toBe('/output/multitrack.webm')
    expect(editor.editing).toBe(false)
    await flushPromises()
    expect(server.count(PREVIEW)).toBe(0)
  })
})
