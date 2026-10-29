// oxlint-disable unicorn/consistent-function-scoping -- stub actions; they use the store once built
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { FieldChange, Fix, JobDraft, JobSettings, JobTemplate, JsonPatchOp } from '@/api/types'
import { notBuilt } from '@/notBuilt'

/**
 * What the tabs edit: one job, or a batch group (a template with per-file overrides, M7). The
 * tabs read and write through the store's `get`, `set` and `patch`, so they work for both.
 */
export type EditorTarget =
  | { kind: 'job'; sourceId: string; job: JobSettings }
  | {
      kind: 'group'
      groupId: string
      template: JobTemplate
      /** Per source id: a JSON patch on that file's job. */
      overrides: Record<string, JsonPatchOp[]>
    }

export interface PatchOptions {
  /** Patches in a row with the same key make one undo step (a slider drag, typing in a field). */
  coalesce?: string
}

/** `audio[2].encoder` (a validation path) → `/audio/2/encoder` (a JSON pointer). */
export function pointerOf(path: string): string {
  return notBuilt('pointerOf', path)
}

/** `/audio/2/encoder` → `audio[2].encoder`. */
export function pathOf(pointer: string): string {
  return notBuilt('pathOf', pointer)
}

export const useEditorStore = defineStore('editor', () => {
  const target = ref<EditorTarget | null>(null)
  /** The last `jobs/draft` answer for the open source: track decisions, naming, notes. */
  const draft = ref<JobDraft | null>(null)
  /** The preset the job was drafted from. */
  const presetId = ref<string | null>(null)
  const loading = ref(false)
  /** `presets/diff` of `currentTemplate` against the preset (the *modified* marker). */
  const presetChanges = ref<FieldChange[]>([])

  const job = computed<JobSettings | null>(() =>
    target.value?.kind === 'job' ? target.value.job : null,
  )
  /** The preset-level settings of the target (for `presets/diff` and *Save as preset*). */
  const currentTemplate = computed<JobTemplate | null>(() => null)
  const modified = computed(() => presetChanges.value.length > 0)
  const canUndo = computed(() => false)
  const canRedo = computed(() => false)

  /** Drafts the source with the preset (default: the default preset). Clears the history. */
  async function open(sourceId: string, preset?: string | null): Promise<void> {
    return notBuilt('editor.open', sourceId, preset)
  }

  /** Drafts the open source again with another preset; one undo step. */
  async function applyPreset(preset: string): Promise<void> {
    return notBuilt('editor.applyPreset', preset)
  }

  /** A queued job back into the editor (its source is opened when it is not). Clears the history. */
  async function loadJob(settings: JobSettings): Promise<void> {
    return notBuilt('editor.loadJob', settings)
  }

  /** The value at a JSON pointer of the target's job, or `undefined`. */
  function get(pointer: string): unknown {
    return notBuilt('editor.get', pointer)
  }

  /** One undo step (or part of the current one, see `PatchOptions.coalesce`). */
  function patch(ops: JsonPatchOp[], options?: PatchOptions): void {
    notBuilt('editor.patch', ops, options)
  }

  /** `patch` with one `replace` (an `add` where the member is missing). */
  function set(pointer: string, value: unknown, options?: PatchOptions): void {
    notBuilt('editor.set', pointer, value, options)
  }

  /** A validation fix: `job` patches the job (one undo step), `settings` the server settings. */
  async function applyFix(fix: Fix): Promise<void> {
    return notBuilt('editor.applyFix', fix)
  }

  function undo(): void {
    notBuilt('editor.undo')
  }

  function redo(): void {
    notBuilt('editor.redo')
  }

  function close(): void {
    notBuilt('editor.close')
  }

  return {
    target,
    draft,
    presetId,
    loading,
    presetChanges,
    job,
    currentTemplate,
    modified,
    canUndo,
    canRedo,
    open,
    applyPreset,
    loadJob,
    get,
    patch,
    set,
    applyFix,
    undo,
    redo,
    close,
  }
})
