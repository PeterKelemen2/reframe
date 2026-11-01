import { createPinia, setActivePinia } from 'pinia'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, configureClient } from '@/api/client'
import { type DevServer, startServer } from '@/api/testing/devServer.mjs'
import { endedTask, http } from '@/api/testing/serverHelpers'
import type { JsonPatchOp } from '@/api/types'
import { pinnedTools } from '@/editor/testing/tools.mjs'

import { useEditorStore } from './editor'
import { suggestedName, templateOfPreset, usePresetsStore } from './presets'

const PORT = 8722
const SOON = { timeout: 15_000, interval: 50 }

let server: DevServer
let sourceId: string

beforeAll(async () => {
  const tools = pinnedTools()
  server = await startServer({
    port: PORT,
    args: ['--fixtures', 'multitrack', ...(tools === null ? [] : ['--tools-dir', tools])],
  })
  const probe = await http<{ task_id: string }>(server, 'POST', '/api/sources', {
    paths: [`${server.media}/multitrack.mkv`],
  })
  const task = await endedTask(server, probe.task_id)
  sourceId = (task.result as { sources: { id: string }[] }).sources[0]?.id ?? ''
}, 120_000)

afterAll(async () => {
  await server.stop()
})

beforeEach(() => {
  setActivePinia(createPinia())
  configureClient({ baseUrl: server.url, token: server.token, fetch: null })
})

let made = 0
function uniqueName(base: string): string {
  made += 1
  return `${base} ${made}`
}

describe('the presets store against reframe-server', () => {
  it('lists the built-ins by category in the server’s order, the default H.265 MKV 1080p', async () => {
    const store = usePresetsStore()
    await store.load()
    expect(store.defaultId).toBe('h265-mkv-1080p')
    expect(store.categories.slice(0, 6).map((group) => group.name)).toEqual([
      'General',
      'Web',
      'Devices',
      'Matroska',
      'Hardware',
      'Production',
    ])
    expect(store.presets.filter((item) => item.built_in)).toHaveLength(26)
  })

  it('offers “Name (2)” for a clash, without case, and renames and deletes a user preset', async () => {
    const store = usePresetsStore()
    await store.load()
    const template = templateOfPreset(store.byId('h265-mkv-1080p')!)
    const name = uniqueName('Clash')
    const created = await store.create({ template, name, category: 'Custom', description: '' })
    expect(created.built_in).toBe(false)

    const clash = await store
      .create({ template, name: name.toUpperCase(), category: 'Custom', description: '' })
      .catch((error: unknown) => error)
    expect(clash).toBeInstanceOf(ApiError)
    expect((clash as ApiError).status).toBe(409)
    expect(suggestedName(clash)).toBe(`${name.toUpperCase()} (2)`)

    const renamed = await store.save({ ...created, name: `${name} renamed` })
    expect(renamed.id).toBe(created.id)
    expect(store.byId(created.id)?.name).toBe(`${name} renamed`)

    await store.remove(created.id)
    expect(store.byId(created.id)).toBeUndefined()
  })

  it('refuses to change a built-in preset', async () => {
    const store = usePresetsStore()
    await store.load()
    const builtIn = store.byId('fast-1080p30')!
    await expect(store.save({ ...builtIn, name: 'Changed' })).rejects.toMatchObject({
      status: 409,
      problem: { code: 'preset.built_in' },
    })
  })

  it('falls back to the built-in default when the default preset is deleted', async () => {
    const store = usePresetsStore()
    await store.load()
    const template = templateOfPreset(store.byId('h265-mkv-1080p')!)
    const created = await store.create({
      template,
      name: uniqueName('Default'),
      category: 'Custom',
      description: '',
    })
    await store.setDefault(created.id)
    expect(store.defaultId).toBe(created.id)
    await store.remove(created.id)
    expect(store.defaultId).toBe('h265-mkv-1080p')
  })

  it('exports a preset and imports it again: rename, replace or skip on the clash', async () => {
    const store = usePresetsStore()
    await store.load()
    const template = templateOfPreset(store.byId('h265-mkv-1080p')!)
    const name = uniqueName('Round trip')
    const created = await store.create({ template, name, category: 'Anime', description: 'd' })
    const blob = await store.exportPresets([created.id])
    const document = JSON.parse(await blob.text()) as { presets: { id: string; name: string }[] }
    expect(document.presets.map((item) => [item.id, item.name])).toEqual([[created.id, name]])
    const file = new File([await blob.text()], 'presets.json', { type: 'application/json' })

    const renamed = await store.importFile(file, 'rename')
    expect(renamed.renamed).toEqual([{ name, new_name: `${name} (2)` }])
    expect(renamed.imported[0]?.id).not.toBe(created.id)
    expect(store.byId(renamed.imported[0]?.id ?? '')?.name).toBe(`${name} (2)`)

    const replaced = await store.importFile(file, 'replace')
    expect(replaced.replaced).toEqual([name])
    expect(replaced.imported[0]?.id).toBe(created.id)

    const skipped = await store.importFile(file, 'skip')
    expect(skipped).toMatchObject({ imported: [], skipped: [name] })
  })

  it('refuses a file that is not a preset file as a whole', async () => {
    const store = usePresetsStore()
    await expect(
      store.importFile(new File(['not json'], 'x.json'), 'rename'),
    ).rejects.toMatchObject({ status: 422, problem: { code: 'presets.import_invalid' } })
  })
})

describe('a preset made from the open job', () => {
  it('is unmodified once the job follows it, and again after an update', async () => {
    const presets = usePresetsStore()
    await presets.load()
    const editor = useEditorStore()
    await editor.open(sourceId, 'h265-mkv-1080p')
    await editor.applyPreset('h264-mkv-1080p')
    expect(editor.presetId).toBe('h264-mkv-1080p')
    editor.set('/video/rate_control/value', 18)
    await vi.waitFor(() => expect(editor.modified).toBe(true), SOON)
    expect(editor.presetChanges.map((change) => change.path)).toEqual(['video.rate_control.value'])

    const created = await presets.create({
      template: editor.currentTemplate!,
      name: uniqueName('From the job'),
      category: 'Custom',
      description: '',
    })
    editor.patch([
      { op: 'replace', path: '/preset_id', value: created.id },
      { op: 'replace', path: '/preset_name', value: created.name },
    ] as JsonPatchOp[])
    await vi.waitFor(() => expect(editor.presetChanges).toEqual([]), SOON)
    expect(editor.preset?.id).toBe(created.id)

    editor.set('/video/rate_control/value', 20)
    await vi.waitFor(() => expect(editor.modified).toBe(true), SOON)
    const current = editor.preset!
    await presets.save({ ...editor.currentTemplate!, ...identity(current) })
    editor.refreshPresetChanges()
    await vi.waitFor(() => expect(editor.presetChanges).toEqual([]), SOON)
    expect(presets.byId(created.id)?.video?.rate_control).toEqual({ mode: 'quality', value: 20 })

    // Undo goes back to the built-in, which the job now differs from again.
    editor.undo()
    editor.undo()
    expect(editor.presetId).toBe('h264-mkv-1080p')
    await vi.waitFor(() => expect(editor.modified).toBe(true), SOON)
  })
})

function identity(preset: { id: string; name: string; category: string; description: string }) {
  return {
    id: preset.id,
    name: preset.name,
    category: preset.category,
    description: preset.description,
    built_in: false,
  }
}
