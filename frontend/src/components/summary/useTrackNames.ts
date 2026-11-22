import { onScopeDispose, shallowRef, watch } from 'vue'

import { apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, Schemas } from '@/api/types'
import { latestRequest } from '@/editor/latest'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'

export type TrackNames = Schemas['TrackNames']

function hasTemplate(name: string | null | undefined): boolean {
  return name !== null && name !== undefined && /[{}]/.test(name)
}

/** Whether a track name of `job` may be a name template, which only the server fills in. */
export function hasNameTemplate(job: JobSettings): boolean {
  return (
    hasTemplate(job.video?.metadata?.name) ||
    (job.audio ?? []).some((track) => hasTemplate(track.metadata?.name)) ||
    (job.subtitles ?? []).some((track) => hasTemplate(track.metadata?.name))
  )
}

/**
 * The track names the editor's job writes (`jobs/track-names`), asked for only while a name
 * has a brace; `null` otherwise, and the names are the job's own. Only the newest answer
 * counts.
 */
export function useTrackNames() {
  const editor = useEditorStore()
  const names = shallowRef<TrackNames | null>(null)

  const request = latestRequest<TrackNames>({
    async send(signal) {
      const job = editor.job as JobSettings
      return unwrap(await apiQuiet.POST('/api/jobs/track-names', { body: { job }, signal }))
    },
    done(value) {
      names.value = value
    },
    failed() {
      // The Summary shows the names as they are typed.
      names.value = null
    },
  })

  let session: number | null = null

  watch(
    () => editor.job,
    (job) => {
      if (job === null || !hasNameTemplate(job)) {
        request.cancel()
        names.value = null
        session = null
        return
      }
      const fresh = session !== editor.session
      session = editor.session
      if (fresh) names.value = null
      request.schedule(fresh ? 0 : EDIT_DEBOUNCE)
    },
    { immediate: true },
  )

  onScopeDispose(() => request.cancel())

  return { names }
}
