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
    // --host 127.0.0.1 is load-bearing on Linux. Without it vite preview binds to
    // "localhost", which resolves to ::1 first on most Linux hosts, while the url below is
    // IPv4 - so Playwright polls a socket nothing is listening on and dies after the full
    // timeout with no useful error. Windows resolves localhost to 127.0.0.1 and hides this.
    command: "npm run build && npm run preview -- --port 4173 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
