import { shallowRef } from 'vue'

/** What the file browser picks: files to open, a folder, or a path to write. */
export type BrowseMode = 'files' | 'folder' | 'save'

export interface BrowseOptions {
  mode: BrowseMode
  /** Files mode: more than one file can be chosen. */
  multiple?: boolean
  /** Files mode: extensions (`mkv` or `.mkv`) the filter shows; none: every listed file. */
  filters?: string[]
  title?: string
  /** Save mode: the path proposed (its folder and its file name). */
  defaultPath?: string
}

export interface BrowseRequest {
  mode: BrowseMode
  multiple: boolean
  /** Lower case, without the dot; empty: no filter. */
  filters: string[]
  title: string | null
  defaultPath: string | null
}

// The server lists these without being asked: reframe.probe.MEDIA_EXTENSIONS.
const MEDIA_EXTENSIONS = new Set([
  '3gp',
  'asf',
  'avi',
  'divx',
  'flv',
  'm2ts',
  'm4v',
  'mkv',
  'mov',
  'mp4',
  'mpeg',
  'mpg',
  'mts',
  'mxf',
  'ogm',
  'ogv',
  'ts',
  'vob',
  'webm',
  'wmv',
])

/**
 * The extensions (`.srt`) the server lists instead of media files for `request`; `null` when
 * it lists media files (no filter, or media extensions only, which the dialog narrows itself).
 */
export function listedExtensions(request: BrowseRequest): string[] | null {
  const { filters } = request
  if (filters.every((ext) => MEDIA_EXTENSIONS.has(ext))) return null
  return filters.map((ext) => `.${ext}`)
}

interface Pending {
  request: BrowseRequest
  resolve(paths: string[] | null): void
}

const pending = shallowRef<Pending | null>(null)

/** The request the dialog shows, or `null` while it is closed. */
export function currentRequest(): BrowseRequest | null {
  return pending.value?.request ?? null
}

/**
 * Opens the file browser; resolves with the chosen paths, or `null` when it was cancelled. A
 * newer request cancels the one that is open.
 */
export function browse(options: BrowseOptions): Promise<string[] | null> {
  pending.value?.resolve(null)
  return new Promise((resolve) => {
    pending.value = {
      request: {
        mode: options.mode,
        multiple: options.multiple ?? false,
        filters: (options.filters ?? []).map((ext) => ext.replace(/^\./, '').toLowerCase()),
        title: options.title ?? null,
        defaultPath: options.defaultPath ?? null,
      },
      resolve,
    }
  })
}

/** Ends `request` with `paths` (`null`: cancelled); does nothing when a newer one replaced it. */
export function finish(request: BrowseRequest, paths: string[] | null): void {
  const open = pending.value
  if (open === null || open.request !== request) return
  pending.value = null
  open.resolve(paths)
}
