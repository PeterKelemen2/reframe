import { onScopeDispose, shallowRef, watch } from 'vue'

import { api, unwrap } from '@/api/client'
import type { EncoderOption } from '@/api/types'
import { latestRequest } from '@/editor/latest'

/** Milliseconds from the last key press in the search to the server's search. */
export const SEARCH_DELAY = 200

/**
 * The server's search over an encoder's advanced options (label, key, CLI name, help), once the
 * typing stops; only the newest query's answer counts. `encoder` is `null` for an encoder
 * without options: nothing matches.
 */
export function useOptionSearch(encoder: () => string | null, query: () => string) {
  /** The matches of `query()`, best first; `null` while they are on their way. */
  const matches = shallowRef<EncoderOption[] | null>(null)

  const request = latestRequest<EncoderOption[]>({
    async send(signal) {
      const params = { path: { encoder_id: encoder() ?? '' }, query: { q: query() } }
      return unwrap(
        await api.GET('/api/definitions/encoders/{encoder_id}/options', { params, signal }),
      )
    },
    done(found) {
      matches.value = found
    },
    failed() {
      matches.value = []
    },
  })

  watch([query, encoder], ([text, id]) => {
    request.cancel()
    matches.value = text !== '' && id === null ? [] : null
    if (text !== '' && id !== null) request.schedule(SEARCH_DELAY)
  })
  onScopeDispose(() => request.cancel())

  return { matches }
}
