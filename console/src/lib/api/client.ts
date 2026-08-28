import type { AdapterMode, PramaanXApiAdapter } from "./adapter";
import { MockPramaanXAdapter } from "./mock-adapter";
import { RestPramaanXAdapter } from "./rest-adapter";

/**
 * Adapter selection.
 *
 * `VITE_PRAMAANX_API_MODE` is read once, at module load, and the resulting mode
 * is exported so the top bar can display it. The mode is not a debug detail: an
 * analyst reading a district page has to know whether the numbers came from the
 * engine or from a fixture, and that answer belongs on screen, not in a
 * console log.
 *
 * REST mode never degrades to mock. If `VITE_PRAMAANX_API_BASE_URL` is missing
 * the app fails loudly at startup rather than showing demo data under a LIVE
 * pill.
 */

const rawMode = (import.meta.env.VITE_PRAMAANX_API_MODE ?? "mock").trim().toLowerCase();
const baseUrl = (import.meta.env.VITE_PRAMAANX_API_BASE_URL ?? "").trim();

function resolve(): { adapter: PramaanXApiAdapter; mode: AdapterMode } {
  if (rawMode === "rest") {
    if (!baseUrl) {
      throw new Error(
        "VITE_PRAMAANX_API_MODE=rest requires VITE_PRAMAANX_API_BASE_URL. " +
          "Refusing to start in REST mode with no engine: falling back to demo data " +
          "would put fixtures behind a LIVE indicator.",
      );
    }
    return {
      adapter: new RestPramaanXAdapter(baseUrl, getSessionToken),
      mode: {
        mode: "rest",
        baseUrl,
        label: "LIVE",
        description: `Reading from the Pramaan-X serving API at ${baseUrl}. Failures surface as errors; nothing falls back to demo data.`,
      },
    };
  }

  if (rawMode !== "mock") {
    // An unrecognised mode is a configuration mistake. Defaulting quietly to
    // REST would be dangerous; defaulting to mock and saying so is not.
    console.warn(`Unknown VITE_PRAMAANX_API_MODE=${rawMode!}; using mock.`);
  }

  return {
    adapter: new MockPramaanXAdapter(),
    mode: {
      mode: "mock",
      label: "SYNTHETIC",
      description:
        "Deterministic demo dataset. Every record is marked is_demo and no value describes any real district.",
    },
  };
}

/**
 * Supplies the caller's session token to the REST adapter.
 *
 * Set by the cloud layer once a session exists. It is a mutable hook rather
 * than an import so `client.ts` does not depend on the auth stack, and so tests
 * can drive the adapter with no session at all.
 */
let sessionTokenProvider: () => Promise<string | null> = async () => null;

export function setSessionTokenProvider(provider: () => Promise<string | null>) {
  sessionTokenProvider = provider;
}

async function getSessionToken(): Promise<string | null> {
  return sessionTokenProvider();
}

const resolved = resolve();

export const apiClient: PramaanXApiAdapter = resolved.adapter;
export const apiMode: AdapterMode = resolved.mode;
export const isDemoMode = resolved.mode.mode === "mock";
