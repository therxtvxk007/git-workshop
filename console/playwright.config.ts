import { defineConfig, devices } from "@playwright/test";

/**
 * Specs are committed as executable documentation of the critical flows.
 * The browser runner is not part of the app runtime: `npm run e2e` installs
 * and drives it separately, and CI does not gate on it.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5173", trace: "on-first-retry" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev -- --port 5173",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    env: { VITE_PRAMAANX_API_MODE: "mock" },
  },
});
