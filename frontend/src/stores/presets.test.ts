import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import { ApiError, configureClient } from '@/api/client'
import { deferred, FakeServer, problem, settle } from '@/api/testing/fakes'
import type { Preset } from '@/api/types'
import { nameConflict, preset, presetList, userPreset } from '@/components/presets/testing'

import { suggestedName, templateOfPreset, usePresetsStore } from './presets'
import { useSystemStore } from './system'
import { useToastStore } from './toasts'

const H265 = preset('h265-mkv-1080p', 'H.265 MKV 1080p', { category: 'Matroska' })
const FAST = preset('fast-1080p30', 'Fast 1080p30', { category: 'General' })
const WEB = preset('creator-1080p60', 'Creator 1080p60', { category: 'Web' })

function names(presets: Preset[]): string[] {
  return presets.map((item) => item.name)
}

describe('the presets store', () => {
  let server: FakeServer

  beforeEach(() => {
    setActivePinia(createPinia())
    server = new FakeServer().on('GET /api/presets', presetList([FAST, H265]))
    configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  })

  it('loads the presets and the default', async () => {
    const store = usePresetsStore()
    await store.load()
    expect(store.loaded).toBe(true)
    expect(names(store.presets)).toEqual(['Fast 1080p30', 'H.265 MKV 1080p'])
    expect(store.defaultId).toBe('h265-mkv-1080p')
  })

  it('reads the list once for callers that ask together, and not again once loaded', async () => {
    const store = usePresetsStore()
    await Promise.all([store.ensureLoaded(), store.ensureLoaded()])
    await store.ensureLoaded()
    expect(server.count('GET /api/presets')).toBe(1)
  })

  it('groups by category: the built-ins in the server order, user presets after them by name, then user-only categories by name', async () => {
    server.on(
      'GET /api/presets',
      presetList([
        FAST,
        WEB,
        H265,
        userPreset('u1', 'zeta', { category: 'Matroska' }),
        userPreset('u2', 'Mine 10'),
        userPreset('u3', 'Mine 9'),
        userPreset('u4', 'Anime', { category: 'Anime' }),
        userPreset('u5', 'alpha', { category: 'Matroska' }),
      ]),
    )
    const store = usePresetsStore()
    await store.load()
    expect(store.categories.map((group) => [group.name, names(group.presets)])).toEqual([
      ['General', ['Fast 1080p30']],
      ['Web', ['Creator 1080p60']],
      ['Matroska', ['H.265 MKV 1080p', 'alpha', 'zeta']],
      ['Anime', ['Anime']],
      ['Custom', ['Mine 9', 'Mine 10']],
    ])
  })

  it('creates a preset from a template and keeps it', async () => {
    const created = userPreset('new', 'Mine')
    server.on('POST /api/presets', () => new Response(JSON.stringify(created), { status: 201 }))
    const store = usePresetsStore()
    await store.load()
    const template = templateOfPreset(H265)
    const answer = await store.create({
      template,
      name: 'Mine',
      category: 'Custom',
      description: '',
    })
    expect(answer.id).toBe('new')
    expect(server.requests.at(-1)?.body).toEqual({
      template,
      name: 'Mine',
      category: 'Custom',
      description: '',
    })
    expect(store.byId('new')?.name).toBe('Mine')
  })

  it('leaves the identity of a preset out of its template', () => {
    const template = templateOfPreset(userPreset('u1', 'Mine', { description: 'x' }))
    for (const key of ['id', 'name', 'category', 'description', 'built_in']) {
      expect(template).not.toHaveProperty(key)
    }
    expect(template.video).toEqual(H265.video)
  })

  it('rejects a name clash without a toast and offers the server’s free name', async () => {
    server.on('POST /api/presets', () => nameConflict('Mine', 'Mine (2)'))
    const store = usePresetsStore()
    const refused = store.create({
      template: templateOfPreset(H265),
      name: 'mine',
      category: 'Custom',
      description: '',
    })
    const error = await refused.catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(suggestedName(error)).toBe('Mine (2)')
    expect(useToastStore().items).toEqual([])
    expect(store.presets).toEqual([])
  })

  it('offers no name for a failure that is not a clash', () => {
    const error = new ApiError(422, {
      type: 'about:blank',
      title: 'A preset needs a name.',
      status: 422,
      code: 'preset.name_empty',
      issues: [
        { severity: 'error', code: 'preset.name_empty', path: 'name', message: 'x', fixes: [] },
      ],
    })
    expect(suggestedName(error)).toBeNull()
    expect(suggestedName(new Error('x'))).toBeNull()
  })

  it('saves a preset under its id and puts the answer in its place', async () => {
    const mine = userPreset('u1', 'Mine')
    server
      .on('GET /api/presets', presetList([FAST, mine]))
      .on('PUT /api/presets/u1', (request) => request.body)
    const store = usePresetsStore()
    await store.load()
    await store.save({ ...mine, name: 'Renamed' })
    expect(server.requests.at(-1)?.body).toMatchObject({ id: 'u1', name: 'Renamed' })
    expect(names(store.presets)).toEqual(['Fast 1080p30', 'Renamed'])
  })

  it('reads the list again when a saved preset is gone, and still rejects', async () => {
    const mine = userPreset('u1', 'Mine')
    server.on('GET /api/presets', presetList([FAST, mine]))
    const store = usePresetsStore()
    await store.load()
    server
      .on('GET /api/presets', presetList([FAST]))
      .on('PUT /api/presets/u1', () => problem(404, 'preset.not_found', 'No preset u1'))
    await expect(store.save(mine)).rejects.toMatchObject({ status: 404 })
    expect(names(store.presets)).toEqual(['Fast 1080p30'])
  })

  it('deletes a preset; deleting the default reads which one the server falls back to', async () => {
    const mine = userPreset('u1', 'Mine')
    const other = userPreset('u2', 'Other')
    server
      .on('GET /api/presets', presetList([H265, mine, other], 'u1'))
      .on('DELETE /api/presets/u2', other)
      .on('DELETE /api/presets/u1', mine)
    const store = usePresetsStore()
    await store.load()

    await store.remove('u2')
    expect(names(store.presets)).toEqual(['H.265 MKV 1080p', 'Mine'])
    expect(server.count('GET /api/presets')).toBe(1)

    server.on('GET /api/presets', presetList([H265]))
    await store.remove('u1')
    expect(server.count('GET /api/presets')).toBe(2)
    expect(store.defaultId).toBe('h265-mkv-1080p')
    expect(names(store.presets)).toEqual(['H.265 MKV 1080p'])
  })

  it('makes a preset the default with the server’s answer', async () => {
    server.on('POST /api/presets/fast-1080p30/default', FAST)
    const store = usePresetsStore()
    await store.load()
    await store.setDefault('fast-1080p30')
    expect(store.defaultId).toBe('fast-1080p30')
  })

  it('imports the chosen file with the clash policy and reads the list again', async () => {
    const imported = userPreset('u9', 'Imported')
    const report = { imported: [imported], renamed: [], replaced: [], skipped: [], issues: [] }
    server.on('POST /api/presets/import', report)
    const store = usePresetsStore()
    await store.load()
    server.on('GET /api/presets', presetList([FAST, H265, imported]))
    const text = JSON.stringify({ schema_version: 1, presets: [imported] })
    const answer = await store.importFile(new File([text], 'mine.json'), 'replace')

    const sent = server.requests.find((request) => request.path === '/api/presets/import')
    expect(sent?.search).toBe('?on_conflict=replace')
    expect(sent?.body).toEqual(JSON.parse(text))
    expect(answer).toEqual(report)
    expect(store.byId('u9')?.name).toBe('Imported')
  })

  it('rejects a file the server cannot read, without a toast', async () => {
    server.on('POST /api/presets/import', () =>
      problem(422, 'presets.import_invalid', 'The preset file is not a JSON object'),
    )
    const store = usePresetsStore()
    const refused = store.importFile(new File(['[1]'], 'bad.json'), 'rename')
    await expect(refused).rejects.toMatchObject({ problem: { code: 'presets.import_invalid' } })
    expect(useToastStore().items).toEqual([])
  })

  it('exports the chosen presets as the server’s document, and every user preset without ids', async () => {
    const document = {
      schema_version: 1,
      presets: [userPreset('u1', 'Mine')],
      default_preset_id: null,
    }
    server.on('GET /api/presets/export', { document, issues: [] })
    const store = usePresetsStore()

    const blob = await store.exportPresets(['u1', 'u2'])
    expect(server.requests.at(-1)?.search).toBe('?ids=u1&ids=u2')
    expect(blob.type).toBe('application/json')
    expect(JSON.parse(await blob.text())).toEqual(document)

    await store.exportPresets([])
    expect(server.requests.at(-1)?.search).toBe('')
    expect(useToastStore().items).toEqual([])
  })

  it('warns that presets of a newer Reframe are in an export', async () => {
    const issue = {
      severity: 'warning',
      code: 'preset.newer_version',
      path: '',
      message: '“Future” is from a newer Reframe',
      fixes: [],
    }
    server.on('GET /api/presets/export', { document: { presets: [] }, issues: [issue] })
    await usePresetsStore().exportPresets([])
    expect(useToastStore().items.map((toast) => [toast.severity, toast.detail])).toEqual([
      ['warn', '“Future” is from a newer Reframe'],
    ])
  })

  it('reads the list only after a change that was sent before it', async () => {
    const answer = deferred<Response>()
    server.on('POST /api/presets', () => answer.promise)
    const store = usePresetsStore()
    const creating = store.create({
      template: templateOfPreset(H265),
      name: 'Mine',
      category: 'Custom',
      description: '',
    })
    const loading = store.load()
    await settle()
    expect(server.count('GET /api/presets')).toBe(0)
    answer.resolve(new Response(JSON.stringify(userPreset('u1', 'Mine')), { status: 201 }))
    await Promise.all([creating, loading])
    expect(server.count('GET /api/presets')).toBe(1)
  })

  it('reads the list again when the event connection opens after a loss, once it was loaded', async () => {
    const store = usePresetsStore()
    const system = useSystemStore()
    system.connection = 'open'
    await nextTick()
    system.connection = 'reconnecting'
    await nextTick()
    system.connection = 'open'
    await nextTick()
    await settle()
    expect(server.count('GET /api/presets')).toBe(0)

    await store.load()
    system.connection = 'reconnecting'
    await nextTick()
    system.connection = 'open'
    await nextTick()
    await settle()
    expect(server.count('GET /api/presets')).toBe(2)
  })
})
