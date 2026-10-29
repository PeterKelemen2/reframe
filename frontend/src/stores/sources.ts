// oxlint-disable unicorn/consistent-function-scoping -- stub actions; they use the store once built
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { Schemas, SourceEntry } from '@/api/types'
import { notBuilt } from '@/notBuilt'

/** A probe that is still running: one task for the paths of one `open`. */
export interface ProbeRun {
  taskId: string
  paths: string[]
  /** 0 to 1, or `null` when the task gives none. */
  progress: number | null
  message: string | null
}

/** The opened sources, the active one, the probes that run, and the batch grouping. */
export const useSourcesStore = defineStore('sources', () => {
  /** In the order they were opened. */
  const entries = ref<SourceEntry[]>([])
  const activeId = ref<string | null>(null)
  const probing = ref<ProbeRun[]>([])
  /** `POST /api/batch/group` over `entries` (the panel's collapsible groups). */
  const grouping = ref<Schemas['BatchGrouping'] | null>(null)

  const active = computed<SourceEntry | null>(
    () => entries.value.find((entry) => entry.id === activeId.value) ?? null,
  )

  /**
   * Probes the paths (files or folders; a task), adds the new sources, and selects the first
   * one when none is active. Resolves with the sources of these paths.
   */
  async function open(paths: string[], options?: { recursive?: boolean }): Promise<SourceEntry[]> {
    return notBuilt('sources.open', paths, options)
  }

  /** `platform.pickFiles`, then `open` (`Ctrl+O`). */
  async function pick(): Promise<void> {
    return notBuilt('sources.pick')
  }

  /** The source of this path, probed first when it is not open. */
  async function ensure(path: string): Promise<SourceEntry> {
    return notBuilt('sources.ensure', path)
  }

  /** Makes the source active and opens it in the editor (`editor.open`). */
  async function select(id: string): Promise<void> {
    return notBuilt('sources.select', id)
  }

  async function remove(id: string): Promise<void> {
    return notBuilt('sources.remove', id)
  }

  /** Reads `GET /api/sources` again. */
  async function refresh(): Promise<void> {
    return notBuilt('sources.refresh')
  }

  /** A new server instance forgot the sources: probe every open path again. */
  async function onServerRestart(): Promise<void> {
    return notBuilt('sources.onServerRestart')
  }

  return {
    entries,
    activeId,
    probing,
    grouping,
    active,
    open,
    pick,
    ensure,
    select,
    remove,
    refresh,
    onServerRestart,
  }
})
