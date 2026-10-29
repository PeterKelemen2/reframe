// oxlint-disable unicorn/consistent-function-scoping -- stub actions; they use the store once built
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { Preset, PresetCreateRequest, Schemas } from '@/api/types'
import { notBuilt } from '@/notBuilt'

export type ImportConflict = 'rename' | 'replace' | 'skip'

export interface PresetCategory {
  name: string
  presets: Preset[]
}

/** Built-in and user presets, and the default one. */
export const usePresetsStore = defineStore('presets', () => {
  const presets = ref<Preset[]>([])
  const defaultId = ref<string | null>(null)
  const loaded = ref(false)

  /** By category, in the server's order. */
  const categories = computed<PresetCategory[]>(() => [])

  function byId(id: string): Preset | undefined {
    return presets.value.find((preset) => preset.id === id)
  }

  async function load(): Promise<void> {
    return notBuilt('presets.load')
  }

  async function create(request: PresetCreateRequest): Promise<Preset> {
    return notBuilt('presets.create', request)
  }

  async function save(preset: Preset): Promise<Preset> {
    return notBuilt('presets.save', preset)
  }

  async function remove(id: string): Promise<void> {
    return notBuilt('presets.remove', id)
  }

  async function setDefault(id: string): Promise<void> {
    return notBuilt('presets.setDefault', id)
  }

  async function importFile(
    file: File,
    onConflict: ImportConflict,
  ): Promise<Schemas['PresetImportReport']> {
    return notBuilt('presets.importFile', file, onConflict)
  }

  /** The export document of these presets, for a download. */
  async function exportPresets(ids: string[]): Promise<Blob> {
    return notBuilt('presets.exportPresets', ids)
  }

  return {
    presets,
    defaultId,
    loaded,
    categories,
    byId,
    load,
    create,
    save,
    remove,
    setDefault,
    importFile,
    exportPresets,
  }
})
