/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for the PolyMind API. Defaults to '/api' (dev proxy / same-origin). */
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
