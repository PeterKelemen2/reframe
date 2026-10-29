/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Which `Platform` implementation the build uses. Set by `.env` / `.env.desktop`. */
  readonly VITE_PLATFORM?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

