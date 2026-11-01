import type { Preset } from '@/api/types'

/** Message lookups the helpers need, from the component's `useI18n`. */
export interface Words {
  /** The word for one key of a settings path (`max_bitrate`), or `undefined`. */
  field(key: string): string | undefined
  none: string
  empty: string
  on: string
  off: string
  /** A settings value that has its own words (`Constant quality CQ 27`), else `undefined`. */
  known?(path: string, value: unknown): string | undefined
}

const VALUE_LIMIT = 80

function fallbackWord(key: string): string {
  const spaced = key.replaceAll('_', ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/**
 * `audio_defaults.codec_rules[0].max_bitrate` as words: "Audio defaults › Codec rule 1 ›
 * Maximum bitrate". A key without a message is shown with spaces for its underscores.
 */
export function pathWords(path: string, words: Words): string {
  const parts: string[] = []
  for (const segment of path.split('.')) {
    const match = /^([^[]*)((?:\[\d+\])*)$/.exec(segment)
    const key = match?.[1] ?? segment
    if (key !== '') parts.push(words.field(key) ?? fallbackWord(key))
    for (const index of (match?.[2] ?? '').matchAll(/\[(\d+)\]/g)) {
      const number = Number(index[1]) + 1
      const last = parts.pop()
      parts.push(last === undefined ? `${number}` : `${last} ${number}`)
    }
  }
  return parts.join(' › ')
}

function clip(text: string): string {
  return text.length > VALUE_LIMIT ? `${text.slice(0, VALUE_LIMIT - 1)}…` : text
}

/**
 * A settings value at `path` in a few words, cut at 80 characters; an object without words of
 * its own as its members (`Preset: light · Tune: film`).
 */
export function valueWords(value: unknown, words: Words, path = ''): string {
  const known = words.known?.(path, value)
  if (known !== undefined) return clip(known)
  if (value === null || value === undefined) return words.none
  if (typeof value === 'boolean') return value ? words.on : words.off
  if (typeof value === 'string') return value === '' ? words.empty : clip(value)
  if (typeof value === 'number') return String(value)
  if (Array.isArray(value)) {
    return value.length === 0
      ? words.none
      : clip(value.map((item) => valueWords(item, words)).join(', '))
  }
  if (typeof value !== 'object') return clip(String(value))
  const members = Object.entries(value as Record<string, unknown>)
    .filter(([, member]) => member !== null && member !== undefined)
    .map(
      ([key, member]) =>
        `${words.field(key) ?? fallbackWord(key)}: ${valueWords(member, words, path ? `${path}.${key}` : key)}`,
    )
  return members.length === 0 ? words.none : clip(members.join(' · '))
}

function normalName(name: string): string {
  return name.trim().replaceAll(/\s+/g, ' ').toLocaleLowerCase()
}

/**
 * The names of the presets in an export file that clash with known presets by id or by name
 * (names compared as the server does: without case and repeated spaces); `null` when the text
 * is not a preset file this check can read (the server then says why).
 */
export function importClashes(text: string, known: Preset[]): string[] | null {
  let document: unknown
  try {
    document = JSON.parse(text)
  } catch {
    return null
  }
  if (typeof document !== 'object' || document === null) return null
  const entries = (document as { presets?: unknown }).presets
  if (!Array.isArray(entries)) return null
  const ids = new Set(known.map((preset) => preset.id))
  const names = new Set(known.map((preset) => normalName(preset.name)))
  const clashes: string[] = []
  for (const entry of entries) {
    if (typeof entry !== 'object' || entry === null) continue
    const { id, name } = entry as { id?: unknown; name?: unknown }
    const byId = typeof id === 'string' && ids.has(id)
    const byName = typeof name === 'string' && names.has(normalName(name))
    if (byId || byName) clashes.push(typeof name === 'string' ? name : String(id))
  }
  return clashes
}

/** A file name for a download of presets: the preset's name, or a general one for several. */
export function exportFileName(presets: Preset[]): string {
  const only = presets.length === 1 ? presets[0] : undefined
  if (only === undefined) return 'reframe-presets.json'
  const safe = [...only.name]
    .map((char) => (char < ' ' || '\\/:*?"<>|'.includes(char) ? '_' : char))
    .join('')
    .trim()
  return `${safe || 'preset'}.json`
}

/** Saves a Blob as a file through the browser's download (an `<a download>`). */
export function download(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.style.display = 'none'
  document.body.append(link)
  link.click()
  link.remove()
  // The download has started from the click; the URL is only needed until then.
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/** Milliseconds from the last naming edit of a preset to its save. */
export const NAMING_SAVE_DELAY = 600
