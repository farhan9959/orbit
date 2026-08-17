import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    pool: "threads",
    // Vitest 4 moved the old `poolOptions.threads` settings to the top level.
    maxWorkers: 1,
    minWorkers: 1,
  },
});
