/** The only place where the web and desktop builds differ. */
export type PlatformKind = 'web' | 'desktop'

export interface Platform {
  kind: PlatformKind
  backend(): Promise<{ baseUrl: string; token?: string }>
  /** Web: the server file-browser dialog. Desktop: the native dialog. */
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
  /** What only the desktop shell has. Web: `null`. */
  desktop: DesktopShell | null
}

/** The server the desktop app talks to (`backend_info`). */
export interface DesktopBackend {
  baseUrl: string
  token: string
  /** `GET /api/health`'s `instance`. */
  instance: string
  /** The app started this server (its sidecar); else it is another front end's owner. */
  owned: boolean
}

export interface DesktopBackendError {
  message: string
  /** The sidecar log, when there is one to read. */
  log: string | null
}

/** The `backend-state` event. */
export type DesktopBackendState =
  | { state: 'starting' }
  | { state: 'ready'; info: DesktopBackend }
  | { state: 'failed'; error: DesktopBackendError }

export interface DesktopSettings {
  /** The tray icon; closing the window can then keep the app running. */
  tray: boolean
}

export interface DesktopShell {
  /** Waits while the backend starts; rejects with a `DesktopBackendError`. */
  backendInfo(): Promise<DesktopBackend>
  /** Every later change: a restarted sidecar, a new owner, a failure. */
  onBackendState(cb: (state: DesktopBackendState) => void): () => void
  /** Runs the start order again after a failure. */
  retryBackend(): Promise<void>
  /** A close of the main window (or the tray's Quit); answer with `quit()` or nothing. */
  onQuitRequested(cb: () => void): () => void
  /** The page answers `onQuitRequested` from now on; before this a close quits at once. */
  quitReady(): Promise<void>
  /** Stops the app's own sidecar (its jobs end interrupted), then exits. */
  quit(): Promise<void>
  /** Keep running in the tray. */
  hideMainWindow(): Promise<void>
  /** Paths from the command line or a second launch, each once. */
  onOpenPaths(cb: (paths: string[]) => void): () => void
  settings(): Promise<DesktopSettings>
  setSettings(settings: DesktopSettings): Promise<DesktopSettings>
  /** Opens (or focuses) the detached preview window of a source. */
  openPreviewWindow(sourceId: string): Promise<void>
}
