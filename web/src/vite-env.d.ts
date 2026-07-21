/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_LOCAL_API?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
