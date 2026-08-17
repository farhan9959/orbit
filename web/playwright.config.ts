import { defineConfig, devices } from "@playwright/test";

/**
 * E2E runs against the built dashboard served by `vite preview`, not the dev server.
 *
 * The dev server transforms on the fly and tolerates things the production bundle does not;
 * testing the preview means the artefact under test is the one that ships in the web
 * container. `reuseExistingServer` is off in CI so a stale server cannot mask a build break.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "line" : [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run build && npm run preview -- --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
