/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CHAT_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
