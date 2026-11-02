import { onScopeDispose, ref, shallowRef, watch } from 'vue'

import { clientBaseUrl } from '@/api/client'
import type { FrameLink } from '@/api/types'
import { usePreviewStore } from '@/stores/preview'

/** The frame's PNG. Rejects when the link has expired (or the server cannot be reached). */
export async function fetchFrame(link: FrameLink): Promise<Blob> {
  // The link is relative to the server, which is not the page's origin in the desktop app.
  const response = await fetch(new URL(link.url, clientBaseUrl() || globalThis.location.origin))
  if (!response.ok) throw new Error(`${response.status} for frame ${link.key}`)
  return response.blob()
}

interface Entry {
  key: string
  bitmap: Promise<ImageBitmap>
  users: number
}

/** A full-resolution frame takes tens of megabytes: the users of one frame share its bitmap. */
const entries = new Map<string, Entry>()

function acquire(link: FrameLink): Entry {
  let entry = entries.get(link.key)
  if (entry === undefined) {
    const created: Entry = {
      key: link.key,
      // Without the option Chromium converts the PNG's cICP colours: the pixels would not be the frame's.
      bitmap: fetchFrame(link).then((blob) =>
        createImageBitmap(blob, { colorSpaceConversion: 'none' }),
      ),
      users: 0,
    }
    created.bitmap.catch(() => {
      if (entries.get(link.key) === created) entries.delete(link.key)
    })
    entries.set(link.key, created)
    entry = created
  }
  entry.users += 1
  return entry
}

function release(entry: Entry): void {
  entry.users -= 1
  if (entry.users > 0) return
  if (entries.get(entry.key) === entry) entries.delete(entry.key)
  entry.bitmap.then(
    (bitmap) => bitmap.close(),
    () => {},
  )
}

/**
 * The decoded pixels of the frame `link()` gives, `null` while they load. A link that has
 * expired asks the preview store for new links once; `failed` when that did not help either.
 */
export function useFrameBitmap(link: () => FrameLink | null) {
  const preview = usePreviewStore()
  const bitmap = shallowRef<ImageBitmap | null>(null)
  const failed = ref(false)
  let held: Entry | null = null
  let retried = false

  async function show(next: FrameLink | null): Promise<void> {
    const previous = held
    held = next === null ? null : acquire(next)
    if (previous !== null) release(previous)
    bitmap.value = null
    failed.value = false
    const own = held
    if (own === null) return
    try {
      const decoded = await own.bitmap
      if (held !== own) return
      bitmap.value = decoded
      retried = false
    } catch {
      if (held !== own) return
      if (retried) {
        failed.value = true
        return
      }
      retried = true
      void preview.reload()
    }
  }

  watch(link, (next) => void show(next), { immediate: true })
  onScopeDispose(() => {
    if (held !== null) release(held)
    held = null
  })

  return { bitmap, failed }
}
