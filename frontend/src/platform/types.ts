/**
 * The only place where the web and desktop builds differ (06 §Platform adapter).
 * `web.ts` and `desktop.ts` implement it. The build picks one with `VITE_PLATFORM`.
 */
export type PlatformKind = 'web' | 'desktop'

export interface Platform {
  kind: PlatformKind
  backend(): Promise<{ baseUrl: string; token?: string }>
  /** Web: the server file-browser dialog (F-5). Desktop: the native dialog. */
  pickFiles(opts: { multiple: boolean; filters?: string[] }): Promise<string[]>
  pickFolder(opts?: { title?: string }): Promise<string | null>
  pickSavePath(opts: { defaultPath: string }): Promise<string | null>
  /** Web: no-op. Returns an unsubscribe function. */
  onFilesDropped(cb: (paths: string[]) => void): () => void
  /** Web: `null` (the action is hidden). */
  revealInFolder(path: string): Promise<void> | null
  openExternal(target: string): Promise<void>
  /** Web: the Notification API. */
  notify(title: string, body: string): Promise<void>
  /** `value` is 0…1, or `null` to clear. Web: shown in `document.title`. */
  setTaskbarProgress(value: number | null): void
}
