// Playwright e2e suite (roadmap t-1029-2): `npm run test:e2e`.
//
// The app is built with VITE_API_URL pointing at a host that does not exist
// (api.e2e.invalid); every API call is answered by context.route() from
// e2e/fixtures/api/*.json, which services/api/scripts/gen_e2e_fixtures.py
// records from the real FastAPI app. No Mongo, Redis or GPU needed.
//
// E2E_REAL_API=1 instead builds against a running local API
// (E2E_API_URL, default http://127.0.0.1:8000) and runs only the smoke spec.
import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT || 4173);
const REAL_API = process.env.E2E_REAL_API === "1";
const API_URL = REAL_API ? process.env.E2E_API_URL || "http://127.0.0.1:8000" : "http://api.e2e.invalid";
const OUT_DIR = REAL_API ? "dist-e2e-real" : "dist-e2e";

export default defineConfig({
  testDir: "./e2e",
  testMatch: REAL_API ? /real-api\.smoke\.spec\.js$/ : /\.spec\.js$/,
  testIgnore: REAL_API ? [] : /real-api\.smoke\.spec\.js$/,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  reporter: process.env.CI
    ? [["list"], ["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // Own outDir so an e2e build never overwrites a real dist/.
    command: `npx vite build --outDir ${OUT_DIR} && npx vite preview --outDir ${OUT_DIR} --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    // Never reuse: a server left running from another build could point at
    // a different API URL and silently bypass the mocks.
    reuseExistingServer: false,
    timeout: 180_000,
    env: {
      VITE_API_URL: API_URL,
      VITE_GOOGLE_CLIENT_ID: "e2e-placeholder.apps.googleusercontent.com",
      // Supabase stays unconfigured: lib/supabaseClient.js exports null.
      VITE_SUPABASE_URL: "",
      VITE_SUPABASE_ANON_KEY: "",
    },
  },
});
