/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PRAMAANX_API_MODE?: string;
  readonly VITE_PRAMAANX_API_BASE_URL?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_MAP_STYLE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
