/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for the PolyMind API. Defaults to '/api' (dev proxy / same-origin). */
  readonly VITE_API_BASE?: string
  /** Bearer token sent to the API when the backend has API_TOKEN set. */
  readonly VITE_API_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
