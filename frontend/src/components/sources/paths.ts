import type { FsRoot } from '@/api/types'

/** The server's separator: its paths use `\` on Windows and `/` elsewhere. */
export function separatorOf(path: string): '/' | '\\' {
  return path.includes('\\') && !path.includes('/') ? '\\' : '/'
}

export function joinPath(folder: string, name: string): string {
  const separator = separatorOf(folder)
  return folder.endsWith(separator) ? `${folder}${name}` : `${folder}${separator}${name}`
}

/** The folder part of `path`, or `null` for a bare name. */
export function folderOf(path: string): string | null {
  const cut = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  if (cut < 0) return null
  return cut === 0 ? path.slice(0, 1) : path.slice(0, cut)
}

/** Lower case, without the dot; empty when the name has none. */
export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot <= 0 ? '' : name.slice(dot + 1).toLowerCase()
}

function within(path: string, folder: string): boolean {
  if (path === folder) return true
  const separator = separatorOf(folder)
  return path.startsWith(folder.endsWith(separator) ? folder : `${folder}${separator}`)
}

export interface Crumb {
  label: string
  path: string
}

/**
 * The way down to `path`: from the deepest root that holds it (named as the root), else from the
 * top of the file system.
 */
export function crumbsOf(path: string, roots: readonly FsRoot[]): Crumb[] {
  const holder = roots
    .filter((root) => within(path, root.path))
    .toSorted((a, b) => b.path.length - a.path.length)[0]
  const separator = separatorOf(path)
  const crumbs: Crumb[] = []
  let current = ''
  let rest = path
  if (holder !== undefined) {
    crumbs.push({ label: holder.name, path: holder.path })
    current = holder.path
    rest = path.slice(holder.path.length)
  } else if (path.startsWith(separator)) {
    crumbs.push({ label: separator, path: separator })
    current = separator
  }
  for (const part of rest.split(/[/\\]/)) {
    if (part === '') continue
    current = current === '' ? part : joinPath(current, part)
    crumbs.push({ label: part, path: current })
  }
  return crumbs
}
