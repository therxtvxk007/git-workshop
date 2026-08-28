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
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Honour a preinstalled browser when one is provided, so the specs can
        // run in an image that already ships Chromium instead of downloading
        // a second copy.
        launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH
          ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH }
          : {},
      },
    },
  ],
  webServer: {
    // `--host 127.0.0.1` is load-bearing. Vite's default bind is `localhost`,
    // which on a GitHub runner resolves to ::1 first, so the dev server ends
    // up listening on IPv6 only while Playwright polls the IPv4 baseURL and
    // times out after 60s having never reached it.
    command: "npm run dev -- --port 5173 --host 127.0.0.1",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    // A cold CI runner installs and transforms on the first request; 60s is
    // enough locally and marginal there.
    timeout: 120_000,
    env: { VITE_PRAMAANX_API_MODE: "mock" },
  },
});
