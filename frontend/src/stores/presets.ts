import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { api, ApiError, apiQuiet, unwrap } from '@/api/client'
import { text } from '@/api/text'
import type { JobTemplate, Preset, PresetCreateRequest, Schemas } from '@/api/types'

import { useSystemStore } from './system'
import { useToastStore } from './toasts'

export type ImportConflict = 'rename' | 'replace' | 'skip'
export type PresetImportReport = Schemas['PresetImportReport']

export interface PresetCategory {
  name: string
  presets: Preset[]
}

const IDENTITY = ['id', 'name', 'category', 'description', 'built_in'] as const

/** The template of a preset: the preset without its id, name, category, description and lock. */
export function templateOfPreset(preset: Preset): JobTemplate {
  const template: Record<string, unknown> = { ...preset }
  for (const key of IDENTITY) delete template[key]
  return template as JobTemplate
}

/** The free name the server offers for a `preset.name_conflict`, or `null` for any other failure. */
export function suggestedName(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.problem.code !== 'preset.name_conflict') return null
  for (const issue of error.problem.issues ?? []) {
    for (const fix of issue.fixes ?? []) {
      const op = fix.patch.find((candidate) => candidate.path === '/name')
      if (op !== undefined && 'value' in op && typeof op.value === 'string') return op.value
    }
  }
  return null
}

const byName = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true })

/**
 * Built-in and user presets, and the default one. There is no preset event: the list is read
 * at the first use, each time the presets view or the picker's list opens, after a change whose
 * answer does not tell the whole list, and when the event connection opens again.
 */
export const usePresetsStore = defineStore('presets', () => {
  const system = useSystemStore()
  const toasts = useToastStore()

  const presets = ref<Preset[]>([])
  const defaultId = ref<string | null>(null)
  const loaded = ref(false)

  /**
   * By category: the built-ins' categories in the server's order, then the others by name. In a
   * category the built-ins come first in the server's order, then the user presets by name.
   */
  const categories = computed<PresetCategory[]>(() => {
    const groups = new Map<string, { builtIn: Preset[]; user: Preset[] }>()
    const group = (name: string) => {
      let found = groups.get(name)
      if (found === undefined) {
        found = { builtIn: [], user: [] }
        groups.set(name, found)
      }
      return found
    }
    for (const preset of presets.value)
      if (preset.built_in) group(preset.category).builtIn.push(preset)
    const builtInCategories = [...groups.keys()]
    for (const preset of presets.value)
      if (!preset.built_in) group(preset.category).user.push(preset)
    const userCategories = [...groups.keys()]
      .filter((name) => !builtInCategories.includes(name))
      .toSorted(byName.compare)
    return [...builtInCategories, ...userCategories].map((name) => {
      const { builtIn, user } = groups.get(name) ?? { builtIn: [], user: [] }
      return {
        name,
        presets: [...builtIn, ...user.toSorted((a, b) => byName.compare(a.name, b.name))],
      }
    })
  })

  function byId(id: string): Preset | undefined {
    return presets.value.find((preset) => preset.id === id)
  }

  // One request at a time: a list read that overtook a change would bring back the old list.
  let chain: Promise<unknown> = Promise.resolve()
  function serial<T>(request: () => Promise<T>): Promise<T> {
    const next = chain.then(request, request)
    chain = next.catch(() => undefined)
    return next
  }

  async function read(): Promise<void> {
    const list = unwrap(await api.GET('/api/presets'))
    presets.value = list.presets
    defaultId.value = list.default_id
    loaded.value = true
  }

  /** Reads the list again. A failure is a toast and keeps the list. */
  async function load(): Promise<void> {
    return serial(read)
  }

  let first: Promise<void> | null = null
  /** `load` once; later calls share the first read. */
  function ensureLoaded(): Promise<void> {
    if (loaded.value) return Promise.resolve()
    first ??= load().finally(() => (first = null))
    return first
  }

  function put(preset: Preset): void {
    const index = presets.value.findIndex((known) => known.id === preset.id)
    if (index === -1) presets.value = [...presets.value, preset]
    else presets.value = presets.value.with(index, preset)
  }

  /** A preset that is gone on the server (another front end deleted it): the list is stale. */
  async function readAfter<T>(request: () => Promise<T>): Promise<T> {
    try {
      return await request()
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) await read().catch(() => undefined)
      throw error
    }
  }

  /**
   * Saves a template as a new user preset. Rejects with the `ApiError` (not toasted): a clash is
   * `preset.name_conflict`, whose free name `suggestedName` reads.
   */
  async function create(request: PresetCreateRequest): Promise<Preset> {
    return serial(async () => {
      const preset = unwrap(await apiQuiet.POST('/api/presets', { body: request }))
      put(preset)
      return preset
    })
  }

  /** Replaces a user preset (a rename too). Rejects as `create`. */
  async function save(preset: Preset): Promise<Preset> {
    return serial(() =>
      readAfter(async () => {
        const saved = unwrap(
          await apiQuiet.PUT('/api/presets/{preset_id}', {
            params: { path: { preset_id: preset.id } },
            body: preset,
          }),
        )
        put(saved)
        return saved
      }),
    )
  }

  /** Deletes a user preset; when it was the default, the server's fallback is read. Toasts a failure. */
  async function remove(id: string): Promise<void> {
    return serial(() =>
      readAfter(async () => {
        unwrap(
          await api.DELETE('/api/presets/{preset_id}', { params: { path: { preset_id: id } } }),
        )
        presets.value = presets.value.filter((preset) => preset.id !== id)
        if (defaultId.value === id) await read()
      }),
    )
  }

  async function setDefault(id: string): Promise<void> {
    return serial(() =>
      readAfter(async () => {
        const preset = unwrap(
          await api.POST('/api/presets/{preset_id}/default', {
            params: { path: { preset_id: id } },
          }),
        )
        defaultId.value = preset.id
      }),
    )
  }

  /**
   * Sends the file as it is (the server reads and migrates it) and reads the list again.
   * Rejects with the `ApiError` of a file the server refuses as a whole (not toasted); what it
   * left out of a file it read is in the report.
   */
  async function importFile(file: File, onConflict: ImportConflict): Promise<PresetImportReport> {
    const body = await file.text()
    return serial(async () => {
      const report = unwrap(
        await apiQuiet.POST('/api/presets/import', {
          params: { query: { on_conflict: onConflict } },
          body: {} as Record<string, never>,
          bodySerializer: () => body,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      await read()
      return report
    })
  }

  /**
   * The export document of these presets (none: every user preset), for a download. Presets of
   * a newer Reframe in it are a warning toast: only that Reframe can import them.
   */
  async function exportPresets(ids: string[]): Promise<Blob> {
    const answer = unwrap(
      await api.GET('/api/presets/export', {
        params: { query: ids.length > 0 ? { ids } : {} },
      }),
    )
    for (const issue of answer.issues) {
      toasts.push({
        severity: 'warn',
        summary: text('presets.export.newer'),
        detail: issue.message,
      })
    }
    return new Blob([`${JSON.stringify(answer.document, null, 2)}\n`], {
      type: 'application/json',
    })
  }

  // Changes made while the connection was lost reach no event: read the list again.
  watch(
    () => system.connection,
    (state, before) => {
      if (state === 'open' && before !== 'open' && loaded.value) void load().catch(() => undefined)
    },
  )

  return {
    presets,
    defaultId,
    loaded,
    categories,
    byId,
    load,
    ensureLoaded,
    create,
    save,
    remove,
    setDefault,
    importFile,
    exportPresets,
  }
})
