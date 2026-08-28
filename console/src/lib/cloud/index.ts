import { LocalCloudBackend } from "./local-backend";
import { SupabaseCloudBackend } from "./supabase-backend";
import type { CloudBackend } from "./types";
import { setSessionTokenProvider } from "@/lib/api/client";

/**
 * Backend selection.
 *
 * Supabase credentials present -> Postgres, with the policies in
 * supabase/migrations doing the enforcing. Absent -> the local backend, and
 * the shell says so, because "your data is in localStorage" is something the
 * person using the console needs to know without reading the source.
 */
const url = (import.meta.env.VITE_SUPABASE_URL ?? "").trim();
const anonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY ?? "").trim();

export const cloud: CloudBackend =
  url && anonKey ? new SupabaseCloudBackend(url, anonKey) : new LocalCloudBackend();

export const cloudIsLocal = cloud.kind === "local";

// The REST adapter needs the caller's bearer token, but must not import the
// auth stack; wiring it here keeps that dependency one-directional.
setSessionTokenProvider(() => cloud.getAccessToken());

export * from "./types";
