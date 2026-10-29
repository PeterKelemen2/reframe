import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { configureClient } from '@/api/client'
import { FakeServer, problem } from '@/api/testing/fakes'
import { stubDom } from '@/components/naming/testing/samples'
import { mountShell } from '@/components/shell/testing'
import { usePresetsStore } from '@/stores/presets'

import PresetImport from './PresetImport.vue'
import { preset, presetList, userPreset } from './testing'

const H265 = preset('h265-mkv-1080p', 'H.265 MKV 1080p')
const MINE = userPreset('u1', 'Mine')
const REPORT = {
  imported: [userPreset('u9', 'Mine (2)')],
  renamed: [{ name: 'Mine', new_name: 'Mine (2)' }],
  replaced: [],
  skipped: [],
  issues: [],
}

let server: FakeServer
const mounted: { unmount(): void }[] = []

beforeAll(stubDom)

beforeEach(() => {
  server = new FakeServer()
    .on('GET /api/presets', presetList([H265, MINE]))
    .on('POST /api/presets/import', REPORT)
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
})

async function mountImport() {
  const result = await mountShell(PresetImport, {
    setup: () => {
      usePresetsStore().presets = [H265, MINE]
    },
  })
  mounted.push(result.wrapper)
  return result.wrapper
}

async function pick(wrapper: Awaited<ReturnType<typeof mountImport>>, text: string) {
  const input = wrapper.find<HTMLInputElement>('.preset-import__input')
  Object.defineProperty(input.element, 'files', {
    value: [new File([text], 'presets.json')],
    configurable: true,
  })
  await input.trigger('change')
  await flushPromises()
}

function imports() {
  return server.requests.filter((request) => request.path === '/api/presets/import')
}

const CLASHING = JSON.stringify({ schema_version: 1, presets: [{ id: 'other', name: 'mine' }] })
const FRESH = JSON.stringify({ schema_version: 1, presets: [{ id: 'new', name: 'New' }] })

describe('the preset import', () => {
  it('opens the file chooser from the button', async () => {
    const wrapper = await mountImport()
    let opened = 0
    wrapper.find('.preset-import__input').element.addEventListener('click', () => (opened += 1))
    await wrapper.find('.preset-import__button').trigger('click')
    expect(opened).toBe(1)
  })

  it('asks what to do with the clashing presets before it imports', async () => {
    const wrapper = await mountImport()
    await pick(wrapper, CLASHING)
    expect(imports()).toEqual([])
    expect(
      [...document.querySelectorAll('[data-list="clashes"] li')].map((li) => li.textContent),
    ).toEqual(['mine'])
    document.querySelector<HTMLInputElement>('input[value="replace"]')?.click()
    await flushPromises()
    document.querySelector<HTMLElement>('.preset-import__run')?.click()
    await flushPromises()
    expect(imports().map((request) => request.search)).toEqual(['?on_conflict=replace'])
    expect(document.querySelector('[data-list="renamed"]')?.textContent).toContain(
      'Mine → Mine (2)',
    )
    expect(wrapper.emitted('imported')).toEqual([[REPORT]])
  })

  it('imports a file without clashes at once', async () => {
    const wrapper = await mountImport()
    await pick(wrapper, FRESH)
    expect(imports().map((request) => request.search)).toEqual(['?on_conflict=rename'])
    expect(document.querySelector('[data-state="report"]')).not.toBeNull()
  })

  it('says why the server refused the whole file', async () => {
    server.on('POST /api/presets/import', () =>
      problem(422, 'presets.import_invalid', 'The preset file is not a JSON object'),
    )
    const wrapper = await mountImport()
    await pick(wrapper, '[1]')
    expect(document.querySelector('.preset-import__failure')?.textContent).toBe(
      'The preset file is not a JSON object',
    )
  })
})
