/**
 * Output paths of one job: the server names the file relative to an output folder
 * (`NameResult.relative_path`, `/`-separated); the job keeps the whole path, so the job's own
 * folder is its path without that relative part.
 */

/** The separator of a path the server sent: `\` for a Windows path, else `/`. */
function separatorOf(path: string): string {
  return path.includes('\\') && !path.includes('/') ? '\\' : '/'
}

function stem(path: string): string {
  const dot = path.lastIndexOf('.')
  const slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  return dot > slash ? path.slice(0, dot) : path
}

function parentOf(path: string, sep: string): string {
  const cut = path.lastIndexOf(sep)
  if (cut < 0) return path
  return cut === 0 ? sep : path.slice(0, cut)
}

/**
 * The folder `path` was written into when `relative` named it. A path that does not end with
 * that name (changed by hand or by a fix) is taken as a file directly in its folder. The
 * extension is ignored, since a container change replaces it.
 */
export function folderOf(path: string | null | undefined, relative?: string | null): string | null {
  if (!path) return null
  const sep = separatorOf(path)
  if (relative) {
    const tailStem = stem(sep + relative.split('/').join(sep))
    const pathStem = stem(path)
    if (pathStem.endsWith(tailStem)) return pathStem.slice(0, -tailStem.length) || sep
  }
  return parentOf(path, sep)
}

/** `path` with `extension` (with or without its dot) in place of its own. */
export function withExtension(path: string, extension: string): string {
  return `${stem(path)}.${extension.replace(/^\./, '')}`
}

/** `relative` (`/`-separated) inside `folder`, with the folder's separator. */
export function joinPath(folder: string, relative: string): string {
  const sep = separatorOf(folder)
  const base = folder.endsWith(sep) ? folder.slice(0, -1) : folder
  return `${base}${sep}${relative.split('/').join(sep)}`
}

/**
 * The job's output path after a naming change: the new relative name in the folder the job's
 * path is in (`previous` named that path), or the server's path when the job has none.
 */
export function nextOutputPath(
  path: string | null | undefined,
  previous: string | null | undefined,
  named: { relative_path: string; path?: string | null },
): string | null {
  const folder = folderOf(path, previous)
  if (folder === null) return named.path ?? null
  return joinPath(folder, named.relative_path)
}
