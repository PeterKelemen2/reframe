// Release-style copies of a media file, for the naming server tests (Node only).
import { copyFile, mkdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'

/** Copies `from` to each path of `relatives` under `root`; resolves with the absolute paths. */
export async function copyAs(from, root, relatives) {
  return Promise.all(
    relatives.map(async (relative) => {
      const target = join(root, relative)
      await mkdir(dirname(target), { recursive: true })
      await copyFile(from, target)
      return target
    }),
  )
}
