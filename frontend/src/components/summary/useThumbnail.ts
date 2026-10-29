import { type MaybeRefOrGetter, onScopeDispose, ref, toValue, watch } from 'vue'

import { apiQuiet, clientBaseUrl, unwrap } from '@/api/client'

/**
 * A frame link is signed for minutes, but the browser keeps the image for an hour
 * (`Cache-Control: max-age=3600`): the same link shows it again without a download.
 */
export const LINK_REUSE_MS = 50 * 60_000

const links = new Map<string, { url: string; at: number }>()

/** Forgets the links of every source (tests). */
export function forgetThumbnails(): void {
  links.clear()
}

/**
 * One source frame of the source (`POST /api/preview/frames`, the middle of the file): its URL,
 * or `null` while it loads, without video, or when no frame could be made.
 */
export function useThumbnail(
  sourceId: MaybeRefOrGetter<string | null>,
  hasVideo: MaybeRefOrGetter<boolean>,
) {
  const url = ref<string | null>(null)
  const loading = ref(false)
  let controller: AbortController | null = null
  let retried = false

  function stop(): void {
    controller?.abort()
    controller = null
    loading.value = false
  }

  async function load(id: string, reuse: boolean): Promise<void> {
    stop()
    const known = links.get(id)
    if (reuse && known !== undefined && Date.now() - known.at < LINK_REUSE_MS) {
      url.value = known.url
      return
    }
    const own = new AbortController()
    controller = own
    url.value = null
    loading.value = true
    try {
      const answer = unwrap(
        await apiQuiet.POST('/api/preview/frames', {
          body: { source_id: id, count: 1 },
          signal: own.signal,
        }),
      )
      if (controller !== own) return
      const frame = answer.frames.find((candidate) => candidate.kind === 'source')
      if (frame === undefined) return
      // The link is relative to the server, which is not the page's origin in the desktop app.
      const absolute = new URL(frame.url, clientBaseUrl() || globalThis.location.origin).href
      links.set(id, { url: absolute, at: Date.now() })
      url.value = absolute
    } catch {
      // No thumbnail is not worth a message: the card shows its placeholder.
    } finally {
      if (controller === own) {
        controller = null
        loading.value = false
      }
    }
  }

  watch(
    () => [toValue(sourceId), toValue(hasVideo)] as const,
    ([id, video]) => {
      retried = false
      if (id === null || !video) {
        stop()
        url.value = null
        return
      }
      void load(id, true)
    },
    { immediate: true },
  )

  /** The image did not load (a link that expired and that the browser no longer holds): asks once more. */
  function failed(): void {
    const id = toValue(sourceId)
    if (id === null) return
    links.delete(id)
    if (retried) {
      url.value = null
      return
    }
    retried = true
    void load(id, false)
  }

  onScopeDispose(stop)

  return { url, loading, failed }
}
