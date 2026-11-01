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
