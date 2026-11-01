import { onScopeDispose, ref, type Ref, shallowRef, watch } from 'vue'

import { ApiError } from '@/api/client'
import type { JobSettings, RenderedTags } from '@/api/types'
import { latestRequest } from '@/editor/latest'
import { EDIT_DEBOUNCE, useEditorStore } from '@/stores/editor'
import { useSettingsStore } from '@/stores/settings'

import { renderedTags } from './requests'

export interface RenderedTagsState {
  tags: Ref<RenderedTags | null>
  /** Why the server gave no values; `null` when it did. */
  failure: Ref<string | null>
  /** A newer job is on its way: what shows is for an older one. */
  pending: Ref<boolean>
}

/**
 * The tags for the open job: at once for a new job, 250 ms after the last edit. Any edit counts,
 * since a tag can name any naming variable. The newest request wins.
 */
export function useRenderedTags(): RenderedTagsState {
  const editor = useEditorStore()
  const settings = useSettingsStore()
  const tags = shallowRef<RenderedTags | null>(null)
  const failure = ref<string | null>(null)
  const pending = ref(false)

  const request = latestRequest<RenderedTags>({
    send: (signal) => renderedTags(editor.job as JobSettings, signal),
    done(answer) {
      tags.value = answer
      failure.value = null
      pending.value = false
    },
    failed(error) {
      pending.value = false
      failure.value =
        error instanceof ApiError ? (error.problem.detail ?? error.problem.title) : String(error)
    },
  })

  // Settings → Output's naming options fill the variables of a job without its own.
  watch(
    () => [editor.session, editor.job, settings.settings] as const,
    ([session, job], previous) => {
      const fresh = previous === undefined || previous[0] !== session
      if (fresh) {
        tags.value = null
        failure.value = null
      }
      if (job === null) {
        request.cancel()
        pending.value = false
        return
      }
      pending.value = true
      request.schedule(fresh ? 0 : EDIT_DEBOUNCE)
    },
    { immediate: true },
  )
  onScopeDispose(() => request.cancel())

  return { tags, failure, pending }
}
