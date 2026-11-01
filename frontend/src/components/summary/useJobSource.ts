import { computed } from 'vue'

import type { MediaSource, SourceEntry } from '@/api/types'
import { useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'

/** The source of the editor's job (a group's shown file), as the sources store holds it. */
export function useJobSource() {
  const editor = useEditorStore()
  const sources = useSourcesStore()

  const sourceId = computed<string | null>(() => editor.target?.sourceId ?? null)
  const entry = computed<SourceEntry | null>(
    () => sources.entries.find((candidate) => candidate.id === sourceId.value) ?? null,
  )
  /** `null` while the source is not open, or when it changed since it was probed. */
  const source = computed<MediaSource | null>(() => entry.value?.source ?? null)

  return { sourceId, entry, source }
}
