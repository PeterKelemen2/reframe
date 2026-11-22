/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Which `Platform` implementation the build uses. Set by `.env` / `.env.desktop`. */
  readonly VITE_PLATFORM?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/** The version the build was stamped with: Vite's `define` replaces the name. */
// oxlint-disable-next-line no-underscore-dangle -- the define naming convention
declare const __REFRAME_VERSION__: string
