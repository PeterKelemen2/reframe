import { ask, open } from '@tauri-apps/plugin-dialog'

import { text } from '@/api/text'

/** What the shell gives for a name that is not valid Unicode: that path does not exist. */
const UNREADABLE = String.fromCodePoint(0xfffd)

/** Says which paths cannot be read, and offers the file dialog for them instead. */
async function offerFileDialog(unreadable: string[], cb: (paths: string[]) => void) {
  const n = unreadable.length
  const chosen = await ask(text('desktop.unreadable.text', { n, paths: unreadable.join('\n') }), {
    title: text('desktop.unreadable.title', { n }),
    kind: 'warning',
    okLabel: text('desktop.unreadable.openFiles'),
    cancelLabel: text('desktop.unreadable.cancel'),
  })
  if (!chosen) return
  const picked = await open({ multiple: true, directory: false })
  if (picked !== null && picked.length > 0) cb(picked)
}

/** Gives `cb` the paths that can be opened; the others are asked about in a native question. */
export async function openReadable(paths: string[], cb: (paths: string[]) => void): Promise<void> {
  const readable = paths.filter((path) => !path.includes(UNREADABLE))
  const unreadable = paths.filter((path) => path.includes(UNREADABLE))
  if (readable.length > 0) cb(readable)
  if (unreadable.length > 0) await offerFileDialog(unreadable, cb)
}
