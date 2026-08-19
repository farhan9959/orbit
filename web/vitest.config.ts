import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // These tests cover pure functions - delta decoding, layout maths, ratio formatting - and
    // touch no DOM. jsdom was costing ~96 s of environment setup per run and intermittently
    // blew the default timeout, reporting "no tests" rather than failing, which is the worst
    // possible failure mode in CI. A component test can opt back in per file with
    // `// @vitest-environment jsdom`.
    environment: "node",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    pool: "threads",
    maxWorkers: 1,
    minWorkers: 1,
  },
});
