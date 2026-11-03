import type { UnlistenFn } from '@tauri-apps/api/event'

/**
 * Turns the listener a Tauri call gives later into the unsubscribe the callers want now. A
 * refused listener is logged under `name`.
 */
export function subscribe(name: string, listening: Promise<UnlistenFn>): () => void {
  let stopped = false
  let unlisten: UnlistenFn | null = null
  listening.then(
    (stop) => {
      if (stopped) return stop()
      unlisten = stop
      return undefined
    },
    (error: unknown) => console.error(`${name} failed`, error),
  )
  return () => {
    stopped = true
    void unlisten?.()
  }
}
