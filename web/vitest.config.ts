import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    pool: "threads",
    poolOptions: { threads: { singleThread: true } },
  },
});
