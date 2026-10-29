import { computed, onScopeDispose, type Ref, shallowRef, watch } from 'vue'

import { apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, Schemas } from '@/api/types'
import { latestRequest } from '@/editor/latest'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'
import { useSourcesStore } from '@/stores/sources'

type JobGeometry = Schemas['JobGeometry']

/** The parts of a job that the output size depends on. */
function geometryKey(job: JobSettings | null): string | null {
  if (job === null) return null
  return JSON.stringify([
    job.source,
    job.range,
    job.dimensions,
    job.filters,
    job.video?.passthrough ?? false,
  ])
}

/**
 * The short side of the output picture (`POST /api/jobs/geometry`, debounced; the newest
 * answer wins), else of the source: what the recommended quality band is chosen by. A 1080p
 * film cropped to 1920×800 and a portrait 1080×1920 clip both get the 1080 band.
 */
export function useOutputLines(): { lines: Ref<number | null> } {
  const editor = useEditorStore()
  const sources = useSourcesStore()
  const answer = shallowRef<JobGeometry | null>(null)

  const request = latestRequest<JobGeometry>({
    async send(signal) {
      const body = { job: editor.job as JobSettings }
      return unwrap(await apiQuiet.POST('/api/jobs/geometry', { body, signal }))
    },
    done(geometry) {
      answer.value = geometry
    },
    failed() {
      answer.value = null
    },
  })

  watch(
    () => [editor.session, geometryKey(editor.job)] as const,
    ([session, key], previous) => {
      if (key === null) {
        request.cancel()
        answer.value = null
        return
      }
      const fresh = session !== previous?.[0]
      if (fresh) answer.value = null
      else if (key === previous?.[1]) return
      request.schedule(fresh ? 0 : EDIT_DEBOUNCE)
    },
    { immediate: true },
  )
  onScopeDispose(() => request.cancel())

  const lines = computed<number | null>(() => {
    const output = answer.value?.geometry
    if (output) return Math.min(output.scaled_width, output.scaled_height)
    const source = answer.value?.source ?? sources.active?.source?.video?.[0] ?? null
    return source ? Math.min(source.width, source.height) : null
  })
  return { lines }
}
