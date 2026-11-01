import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { Fix, JobSettings } from '@/api/types'
import { mountBase } from '@/components/base/testing'
import TagsTab from '@/components/editor/tabs/TagsTab.vue'
import { issue, sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { type NamingVariable, useSystemStore } from '@/stores/system'
import { useValidationStore } from '@/stores/validation'

import { renderedFor } from './testing'

const ROUTE = 'POST /api/jobs/tags'

let server: FakeServer
let job: JobSettings
const mounted: VueWrapper[] = []

beforeEach(() => {
  job = sampleJob()
  server = new FakeServer()
    .on('POST /api/jobs/draft', () => sampleDraft(job))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
    .on(ROUTE, (request) => renderedFor((request.body as { job: JobSettings }).job))
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountTab() {
  const wrapper = mountBase(TagsTab)
  mounted.push(wrapper)
  useSystemStore().namingVariables = [
    { name: 'name', kind: 'text', description: 'Movie title or show name' },
    { name: 'season', kind: 'number', description: 'Season number' },
  ] as NamingVariable[]
  const editor = useEditorStore()
  await editor.open('src')
  await vi.waitFor(() => expect(server.count(ROUTE)).toBeGreaterThan(0))
  await flushPromises()
  return { wrapper, editor }
}

const tag = (wrapper: VueWrapper, name: string) => wrapper.find(`[data-tag="${name}"]`)

it('has the eight tags', async () => {
  const { wrapper } = await mountTab()
  expect(wrapper.findAll('[data-tag]').map((element) => element.attributes('data-tag'))).toEqual([
    'title',
    'actors',
    'director',
    'release_date',
    'comment',
    'genre',
    'description',
    'plot',
  ])
})

it('writes what is typed as one undo step; an emptied field unsets the tag', async () => {
  const { wrapper, editor } = await mountTab()
  const input = tag(wrapper, 'director').find('input')
  await input.setValue('Me')
  await input.setValue('Mel')
  await input.trigger('blur')
  expect(editor.job?.tags?.director).toBe('Mel')
  await input.setValue('')
  await input.trigger('blur')
  expect(editor.job?.tags?.director).toBeNull()
  editor.undo()
  expect(editor.job?.tags?.director).toBe('Mel')
  editor.undo()
  expect(editor.job?.tags?.director).toBeNull()
  expect(editor.canUndo).toBe(false)
})

it('offers the naming variables after {', async () => {
  const { wrapper } = await mountTab()
  const input = tag(wrapper, 'title').find('input')
  input.element.value = '{na'
  input.element.setSelectionRange(3, 3)
  await input.trigger('input')
  await flushPromises()
  expect(
    tag(wrapper, 'title')
      .findAll('[role="option"]')
      .map((o) => o.text()),
  ).toEqual([expect.stringContaining('{name}')])
})

it("shows the value as it will be written and the source's value", async () => {
  const { wrapper, editor } = await mountTab()
  editor.set('/tags/title', '{name} (cut)')
  await vi.waitFor(() =>
    expect(tag(wrapper, 'title').find('[data-field="written"]').text()).toBe('multitrack (cut)'),
  )
  expect(tag(wrapper, 'title').find('[data-field="source"]').text()).toBe('Source title')
  expect(tag(wrapper, 'genre').find('[data-field="written"]').text()).toBe('Not written')
  expect(tag(wrapper, 'genre').find('[data-field="source"]').text()).toBe('None')
})

it('says that the source values are copied first while passthru is on', async () => {
  const { wrapper, editor } = await mountTab()
  expect(wrapper.find('[data-note="passthru"]').exists()).toBe(true)
  expect(tag(wrapper, 'title').find('[data-field="written"]').text()).toBe(
    'Source title (copied from the source)',
  )
  editor.set('/output/passthru_metadata', false)
  await flushPromises()
  expect(wrapper.find('[data-note="passthru"]').exists()).toBe(false)
})

it('shows a template error at its field, once, with its fix', async () => {
  const fix: Fix = {
    label: 'Use {name}',
    target: 'job',
    patch: [{ op: 'replace', path: '/tags/title', value: '{name}' }],
  }
  const error = { ...issue('naming.unknown_variable', 'tags.title'), fixes: [fix] }
  server.on(ROUTE, (request) => renderedFor((request.body as { job: JobSettings }).job, [error]))
  const { wrapper, editor } = await mountTab()
  useValidationStore().issues = [error]
  await flushPromises()
  const field = wrapper.find('[data-path="tags.title"]')
  expect(field.findAll('.rf-field__issue')).toHaveLength(1)
  expect(field.find('.rf-field__issue').text()).toContain('naming.unknown_variable at tags.title')
  expect(wrapper.find('[data-path="tags.genre"]').findAll('.rf-field__issue')).toHaveLength(0)
  const button = field.findAll('button').find((b) => b.text() === 'Use {name}')
  await button!.trigger('click')
  expect(editor.job?.tags?.title).toBe('{name}')
})
