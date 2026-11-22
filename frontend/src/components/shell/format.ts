/** The last part of a path; the server's paths may use `/` or `\`. */
export function fileName(path: string): string {
  const parts = path.split(/[/\\]/)
  return parts.findLast((part) => part !== '') ?? path
}

/** `1:02:03` for an hour or more, `2:03` below; `null` for an unknown duration. */
export function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return null
  }
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = String(total % 60).padStart(2, '0')
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`
}

/** `useI18n().n` with formatting options, for the formatters that show a number. */
export type FormatNumber = (value: number, options: Intl.NumberFormatOptions) => string

/**
 * Names or values as the locale lists them: `and` reads them as one part of a sentence
 * (`ffmpeg and ffprobe`), `plain` only separates them (`mkv, mp4`).
 */
export function formatList(
  items: readonly string[],
  locale: string,
  kind: 'and' | 'plain' = 'plain',
): string {
  const options: Intl.ListFormatOptions =
    kind === 'and' ? { type: 'conjunction', style: 'long' } : { type: 'unit', style: 'short' }
  return new Intl.ListFormat(locale, options).format(items)
}
